//! Read-only GitHub queries through the `gh` CLI. Only list commands with an
//! explicit field list run here; tokens never reach this process's output.

use serde_json::{json, Value};
use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use crate::Config;

const TTL: Duration = Duration::from_secs(60);

/// Mirrors `REJECT_LABELS` in `src/local_first/github_issue_queue.py`.
const REJECT_LABELS: &[&str] = &[
    "blocked", "epic", "pr:open", "dependency:blocked", "type:epic", "status:blocked",
    "status:waiting", "agent:pr-open", "agent:blocked", "agent:analyzing",
    "agent:claude-running", "agent:escalate",
];

/// Mirrors `TRIAGE_SKIP_LABELS` in `src/local_first/issue_triage.py` (minus the worker's own labels).
const TRIAGE_SKIP_LABELS: &[&str] = &[
    "type:epic", "master", "ws:server", "observe-only", "status:roadmap", "ci-blocked",
    "external-action", "status:external-action", "archive", "duplicate", "agent:pilot",
];

/// Mirrors `DEFAULT_TRUSTED_AUTHORS` in `src/local_first/issue_triage.py`.
const TRUSTED_AUTHORS: &[&str] = &["uezeyiraydin-cell", "apoman74-art"];

const GH_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Default)]
struct Slot {
    value: Option<Value>,
    fetched: Option<Instant>,
    refreshing: bool,
}

/// GitHub data refreshed in the background, so a slow `gh` never blocks the page.
pub struct Cache {
    slot: Arc<Mutex<Slot>>,
}

impl Cache {
    pub fn new() -> Self {
        Cache { slot: Arc::new(Mutex::new(Slot::default())) }
    }

    pub fn get(&self, cfg: &Arc<Config>) -> Value {
        let mut slot = self.slot.lock().unwrap_or_else(|e| e.into_inner());
        let stale = slot.fetched.map_or(true, |at| at.elapsed() >= TTL);
        if stale && !slot.refreshing {
            slot.refreshing = true;
            let (shared, cfg) = (Arc::clone(&self.slot), Arc::clone(cfg));
            std::thread::spawn(move || {
                let value = fetch(&cfg);
                let mut slot = shared.lock().unwrap_or_else(|e| e.into_inner());
                *slot = Slot { value: Some(value), fetched: Some(Instant::now()), refreshing: false };
            });
        }
        slot.value.clone().unwrap_or_else(|| {
            json!({"ok": false, "loading": true, "error": "GitHub wird geladen", "open_issues": [], "worker_prs": []})
        })
    }

    /// Blocking fetch for the one-shot JSON print.
    pub fn fetch_now(cfg: &Config) -> Value {
        fetch(cfg)
    }
}

fn gh(cfg: &Config, args: &[&str]) -> Result<Value, String> {
    let mut child = Command::new(&cfg.gh)
        .args(args)
        .env("GH_PROMPT_DISABLED", "1")
        .env("GH_NO_UPDATE_NOTIFIER", "1")
        .env("NO_COLOR", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("gh nicht startbar: {}", e.kind()))?;
    let mut stdout = child.stdout.take().ok_or("gh ohne Ausgabe")?;
    let mut stderr = child.stderr.take().ok_or("gh ohne Ausgabe")?;
    let out_reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = stdout.read_to_end(&mut buf);
        buf
    });
    let err_reader = std::thread::spawn(move || {
        let mut buf = String::new();
        let _ = stderr.read_to_string(&mut buf);
        buf
    });
    let deadline = Instant::now() + GH_TIMEOUT;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(100)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("gh antwortet nicht (Zeitlimit)".to_string());
            }
        }
    };
    let stdout = out_reader.join().unwrap_or_default();
    let stderr = err_reader.join().unwrap_or_default();
    if !status.success() {
        let first = stderr.lines().next().unwrap_or("").to_string();
        return Err(crate::local::redact(&format!("gh fehlgeschlagen: {first}")));
    }
    serde_json::from_slice(&stdout).map_err(|_| "gh lieferte kein JSON".to_string())
}

fn fetch(cfg: &Config) -> Value {
    let open = gh(cfg, &[
        "issue", "list", "-R", &cfg.repo, "--state", "open",
        "--limit", "200", "--json", "number,title,labels,url,author,createdAt,updatedAt",
    ]);
    let prs = gh(cfg, &[
        "pr", "list", "-R", &cfg.repo, "--state", "all", "--author", &cfg.worker_login,
        "--limit", "200", "--json", "number,title,state,headRefName,url,createdAt,mergedAt,closedAt",
    ]);
    // Claude's reasons live in the triage comments; only the excluded issues need them.
    let reasons = gh(cfg, &[
        "issue", "list", "-R", &cfg.repo, "--state", "open", "--label", "agent:not-suitable",
        "--limit", "200", "--json", "number,comments",
    ])
    .ok()
    .and_then(|v| v.as_array().cloned())
    .unwrap_or_default();
    let error = [&open, &prs].iter().find_map(|r| r.as_ref().err().cloned());
    let open: Vec<Value> = open
        .ok()
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
        .into_iter()
        .map(|issue| {
            let reason = reasons.iter().find(|r| r["number"] == issue["number"]).and_then(triage_reason);
            let mut issue = annotate_issue(issue);
            if let Some(reason) = reason {
                issue["waiting_reason"] = json!(format!("Triage: {reason}"));
            }
            issue
        })
        .collect();
    let prs: Vec<Value> = prs
        .ok()
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
        .into_iter()
        .filter_map(|mut pr| {
            let issue = issue_from_branch(pr["headRefName"].as_str()?)?;
            pr["issue"] = json!(issue);
            Some(pr)
        })
        .collect();
    json!({"ok": error.is_none(), "error": error, "open_issues": open, "worker_prs": prs})
}

const TRIAGE_MARKER: &str = "<!-- TIM_QWEN_TRIAGE_V1 -->";

/// The `Begründung:` line of the newest worker triage comment on an issue.
pub fn triage_reason(issue: &Value) -> Option<String> {
    issue["comments"].as_array()?.iter().rev().find_map(|c| {
        let body = c["body"].as_str()?;
        if !body.contains(TRIAGE_MARKER) {
            return None;
        }
        let line = body.lines().find_map(|l| l.trim().strip_prefix("Begründung:"))?;
        Some(crate::local::redact(line.trim()))
    })
}

/// `codex/issue-166-qwen` -> 166, the branch scheme of `run_mac_qwen_issue.py`.
pub fn issue_from_branch(branch: &str) -> Option<u64> {
    branch.strip_prefix("codex/issue-")?.strip_suffix("-qwen")?.parse().ok()
}

fn label_names(issue: &Value) -> Vec<String> {
    issue["labels"]
        .as_array()
        .map(|labels| {
            labels
                .iter()
                .filter_map(|l| l.as_str().or_else(|| l["name"].as_str()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

/// Adds `stage`, `eligible`, `priority` and `waiting_reason` the way the worker's
/// queue and triage decide: `ready` (the worker takes it), `triage` (Claude still
/// has to judge it), `blocked` (two failed attempts) or `skipped`.
pub fn annotate_issue(mut issue: Value) -> Value {
    let labels = label_names(&issue);
    let has = |l: &str| labels.iter().any(|x| x == l);
    let author = issue["author"]["login"].as_str().unwrap_or("").to_lowercase();
    let priority = if has("priority:p0") { Some("P0") } else if has("priority:p1") { Some("P1") } else { None };
    let rejected: Vec<&str> = REJECT_LABELS.iter().copied().filter(|l| has(l)).collect();
    let skipped: Vec<&str> = TRIAGE_SKIP_LABELS.iter().copied().filter(|l| has(l)).collect();
    let (stage, reason) = if has("agent:blocked") {
        ("blocked", Some("2 Versuche gescheitert · agent:blocked entfernen gibt 2 neue".to_string()))
    } else if has("agent:not-suitable") {
        ("skipped", Some("Triage: nicht geeignet".to_string()))
    } else if has("agent:qwen-ready") || has("agent:qwen-hard") {
        if !rejected.is_empty() {
            ("skipped", Some(format!("gesperrt durch {}", rejected.join(", "))))
        } else if !has("status:ready") {
            ("skipped", Some("status:ready fehlt".to_string()))
        } else if priority.is_none() {
            ("skipped", Some("Priorität p0/p1 fehlt".to_string()))
        } else {
            ("ready", None)
        }
    } else if !rejected.is_empty() {
        ("skipped", Some(format!("gesperrt durch {}", rejected.join(", "))))
    } else if !skipped.is_empty() {
        ("skipped", Some(format!("keine Triage wegen {}", skipped.join(", "))))
    } else if !TRUSTED_AUTHORS.contains(&author.as_str()) {
        ("skipped", Some(format!("Autor {} nicht freigegeben", if author.is_empty() { "?" } else { &author })))
    } else {
        ("triage", Some("wartet auf Triage durch Claude".to_string()))
    };
    issue["labels"] = json!(labels);
    issue["priority"] = json!(priority);
    issue["stage"] = json!(stage);
    issue["eligible"] = json!(stage == "ready");
    issue["server"] = json!(has("agent:qwen-hard"));
    issue["waiting_reason"] = json!(reason);
    issue
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn branch_to_issue() {
        assert_eq!(issue_from_branch("codex/issue-166-qwen"), Some(166));
        assert_eq!(issue_from_branch("codex/mac-issue-worker"), None);
        assert_eq!(issue_from_branch("claude/issue-12-fix"), None);
    }

    #[test]
    fn eligibility_matches_worker_queue() {
        let ready = annotate_issue(json!({"labels": [
            {"name": "agent:qwen-ready"}, {"name": "status:ready"}, {"name": "priority:p1"}]}));
        assert_eq!(ready["eligible"], json!(true));
        assert_eq!(ready["priority"], json!("P1"));

        let blocked = annotate_issue(json!({"labels": ["agent:qwen-ready", "status:ready", "priority:p0", "agent:blocked"]}));
        assert_eq!(blocked["eligible"], json!(false));
        assert!(blocked["waiting_reason"].as_str().unwrap().contains("agent:blocked"));

        let no_prio = annotate_issue(json!({"labels": ["agent:qwen-ready", "status:ready"]}));
        assert_eq!(no_prio["waiting_reason"], json!("Priorität p0/p1 fehlt"));
    }

    #[test]
    fn reads_triage_reason_from_marker_comment() {
        let issue = json!({"comments": [
            {"body": "Begründung: von Hand"},
            {"body": "<!-- TIM_QWEN_TRIAGE_V1 -->\nAutomatische Triage: Kein Auftrag.\n\nBegründung: Epic mit vielen Teilen\n"},
        ]});
        assert_eq!(triage_reason(&issue).as_deref(), Some("Epic mit vielen Teilen"));
        assert_eq!(triage_reason(&json!({"comments": []})), None);
    }

    #[test]
    fn hard_issues_go_to_server() {
        let hard = annotate_issue(json!({"labels": ["agent:qwen-hard", "status:ready", "priority:p1"]}));
        assert_eq!(hard["stage"], json!("ready"));
        assert_eq!(hard["server"], json!(true));
        let mac = annotate_issue(json!({"labels": ["agent:qwen-ready", "status:ready", "priority:p1"]}));
        assert_eq!(mac["server"], json!(false));
    }

    #[test]
    fn stages_follow_triage() {
        let author = json!({"login": "uezeyiraydin-cell"});
        let fresh = annotate_issue(json!({"labels": [], "author": author}));
        assert_eq!(fresh["stage"], json!("triage"));
        let stranger = annotate_issue(json!({"labels": [], "author": {"login": "someone"}}));
        assert_eq!(stranger["stage"], json!("skipped"));
        let epic = annotate_issue(json!({"labels": ["type:epic"], "author": author}));
        assert_eq!(epic["stage"], json!("skipped"));
        let unfit = annotate_issue(json!({"labels": ["agent:not-suitable"], "author": author}));
        assert_eq!(unfit["waiting_reason"], json!("Triage: nicht geeignet"));
        let blocked = annotate_issue(json!({"labels": ["agent:blocked"], "author": author}));
        assert_eq!(blocked["stage"], json!("blocked"));
    }
}
