//! Read-only view of the worker's local files: LaunchAgent, locks, worktrees,
//! run evidence and the newline-delimited JSON log. Nothing here writes.

use serde_json::{json, Map, Value};
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::UNIX_EPOCH;

use crate::Config;

const LOG_TAIL_BYTES: u64 = 2 * 1024 * 1024;

pub fn read_json(path: &Path) -> Option<Value> {
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok().filter(Value::is_object)
}

fn secs(time: std::io::Result<std::time::SystemTime>) -> Option<u64> {
    time.ok()?.duration_since(UNIX_EPOCH).ok().map(|d| d.as_secs())
}

fn mtime(path: &Path) -> Option<u64> {
    secs(fs::metadata(path).and_then(|m| m.modified()))
}

fn created(path: &Path) -> Option<u64> {
    secs(fs::metadata(path).and_then(|m| m.created()))
}

/// Removes anything that looks like a credential before text leaves the process.
pub fn redact(text: &str) -> String {
    let mut out = Vec::new();
    for word in text.split(' ') {
        let lower = word.to_ascii_lowercase();
        let secretish = ["ghp_", "gho_", "ghs_", "ghu_", "github_pat_", "sk-", "xox"]
            .iter()
            .any(|p| lower.trim_start_matches(|c: char| !c.is_ascii_alphanumeric()).starts_with(p));
        let assignment = ["token", "password", "secret", "api_key", "apikey", "authorization"]
            .iter()
            .any(|k| lower.contains(k) && (lower.contains('=') || lower.contains(':')) && word.len() > k.len() + 2);
        out.push(if secretish || assignment { "<REDACTED>".to_string() } else { word.to_string() });
    }
    let joined = out.join(" ");
    joined.chars().take(600).collect()
}

fn text(value: &Value, key: &str) -> Option<String> {
    match value.get(key)? {
        Value::String(s) if s.is_empty() => None,
        Value::String(s) => Some(redact(s)),
        Value::Null => None,
        other => Some(other.to_string()),
    }
}

#[cfg(test)]
fn lock_pid(path: &Path) -> Option<u32> {
    let raw = fs::read_to_string(path).ok()?;
    raw.trim().trim_start_matches("pid=").parse().ok()
}

fn launch_agent(label: &str) -> Value {
    let output = Command::new("/bin/launchctl").args(["list", label]).output();
    let Ok(output) = output else { return json!({"loaded": false}) };
    if !output.status.success() {
        return json!({"loaded": false});
    }
    let body = String::from_utf8_lossy(&output.stdout);
    let field = |name: &str| -> Option<i64> {
        body.lines()
            .find(|l| l.trim_start().starts_with(&format!("\"{name}\"")))
            .and_then(|l| l.split('=').nth(1))
            .and_then(|v| v.trim().trim_end_matches(';').trim().parse().ok())
    };
    let pid = field("PID");
    json!({"loaded": true, "pid": pid, "running": pid.is_some(), "last_exit": field("LastExitStatus")})
}

/// Plain HTTP/1.0 GET against a local Ollama endpoint; `None` when it does not answer.
fn http_get(url: &str, path: &str) -> Option<String> {
    use std::io::Write;
    use std::net::TcpStream;
    let host = url.trim_start_matches("http://").trim_end_matches('/');
    let addr = host.parse().ok()?;
    let mut stream = TcpStream::connect_timeout(&addr, std::time::Duration::from_secs(2)).ok()?;
    stream.set_read_timeout(Some(std::time::Duration::from_secs(3))).ok()?;
    write!(stream, "GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n").ok()?;
    // Stop at Content-Length: a complete reply must not become a timeout just
    // because a proxy keeps its side of the connection open.
    use std::io::BufRead;
    let mut reader = std::io::BufReader::new(stream);
    let mut line = String::new();
    reader.read_line(&mut line).ok()?;
    if line.split_whitespace().nth(1) != Some("200") { return None; }
    let mut length = None;
    let mut header_bytes = line.len();
    loop {
        line.clear();
        if reader.read_line(&mut line).ok()? == 0 { return None; }
        header_bytes += line.len();
        if header_bytes > 16_384 { return None; }
        if line == "\r\n" || line == "\n" { break; }
        if let Some((key, value)) = line.split_once(':') {
            if key.eq_ignore_ascii_case("content-length") { length = Some(value.trim().parse::<usize>().ok()?); }
        }
    }
    const MAX_BODY: usize = 2 * 1024 * 1024;
    let mut body = Vec::new();
    if let Some(length) = length {
        if length > MAX_BODY { return None; }
        body.resize(length, 0);
        reader.read_exact(&mut body).ok()?;
    } else {
        reader.take((MAX_BODY + 1) as u64).read_to_end(&mut body).ok()?;
        if body.len() > MAX_BODY { return None; }
    }
    String::from_utf8(body).ok()
}

fn get_json(url: &str, path: &str) -> Option<Value> {
    http_get(url, path).and_then(|b| serde_json::from_str::<Value>(&b).ok())
}

fn lists_model(list: &Value, model: &str) -> bool {
    list["models"].as_array().map_or(false, |models| {
        models.iter().any(|m| m["name"].as_str() == Some(model) || m["model"].as_str() == Some(model))
    })
}

fn ollama(url: &str, model: &str) -> Value {
    match get_json(url, "/api/tags") {
        Some(tags) => json!({"reachable": true, "model": model, "model_installed": lists_model(&tags, model)}),
        None => json!({"reachable": false, "model": model, "model_installed": false}),
    }
}

/// The server model behind the SSH tunnel: reachable, installed, and loaded ("warm") right now.
fn server_model(url: &str, model: &str) -> Value {
    let Some(tags) = get_json(url, "/api/tags") else {
        return json!({"reachable": false, "model": model, "model_installed": false, "warm": null, "expires_at": null});
    };
    let loaded = get_json(url, "/api/ps").filter(|v| v["models"].is_array());
    let entry = loaded.as_ref().and_then(|v| v["models"].as_array()).and_then(|models| {
        models.iter().find(|m| m["name"].as_str() == Some(model) || m["model"].as_str() == Some(model)).cloned()
    });
    json!({
        "reachable": true,
        "model": model,
        "model_installed": lists_model(&tags, model),
        "warm": loaded.as_ref().map(|_| entry.is_some()),
        "expires_at": entry.as_ref().map(|e| e["expires_at"].clone()),
        "size_bytes": entry.as_ref().map(|e| e["size"].clone()),
    })
}

/// Every `.tim/local-first` directory that may hold evidence for an issue run.
fn evidence_roots(cfg: &Config, issue: u64) -> Vec<(String, PathBuf)> {
    // GitHub issue evidence lives in Application Support. Reading the source checkout
    // under Documents is unnecessary and can block on a macOS privacy prompt.
    let mut roots = Vec::new();
    let archive = cfg.state_dir.join("archive");
    if let Ok(entries) = fs::read_dir(&archive) {
        let prefix = format!("issue-{issue}-qwen-");
        let mut names: Vec<String> = entries
            .filter_map(|e| e.ok()?.file_name().into_string().ok())
            .filter(|n| n.starts_with(&prefix))
            .collect();
        names.sort();
        for name in names {
            roots.push((format!("Archiv {name}"), archive.join(&name).join(".tim/local-first")));
        }
    }
    roots.push(("Worktree".to_string(), cfg.state_dir.join(format!("worktrees/issue-{issue}-qwen/.tim/local-first"))));
    roots
}

fn files_for(dir: &Path, task: &str) -> Vec<PathBuf> {
    let Ok(entries) = fs::read_dir(dir) else { return vec![] };
    let mut files: Vec<PathBuf> = entries
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| {
            let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
            name.ends_with(".json") && (name == format!("{task}.json") || name.starts_with(&format!("{task}.")))
        })
        .collect();
    files.sort_by_key(|p| mtime(p));
    files
}

/// Collects the events and helper usage of one issue across all its attempts.
pub fn issue_runs(cfg: &Config, issue: u64) -> Value {
    let task = format!("github-issue-{issue}");
    let mut events: Vec<Value> = Vec::new();
    let mut helpers: Vec<String> = Vec::new();
    let add_helper = |name: &str, helpers: &mut Vec<String>| {
        if !helpers.iter().any(|h| h == name) {
            helpers.push(name.to_string());
        }
    };
    let mut attempts = 0;
    for (place, root) in evidence_roots(cfg, issue) {
        if !root.exists() {
            continue;
        }
        let mut touched = false;
        let push = |at: Option<u64>, phase: &str, detail: Option<String>, events: &mut Vec<Value>| {
            events.push(json!({"at": at, "phase": phase, "detail": detail, "place": place}));
        };
        for dir in ["developer-inbox", "developer-processed"] {
            for f in files_for(&root.join(dir), &task) {
                touched = true;
                let v = read_json(&f).unwrap_or_default();
                let label = if dir == "developer-inbox" { "Auftrag an Entwickler übergeben" } else { "Entwickler-Auftrag verarbeitet" };
                push(mtime(&f), label, text(&v, "objective"), &mut events);
            }
        }
        for f in files_for(&root.join("blockers/requests"), &task) {
            touched = true;
            let v = read_json(&f).unwrap_or_default();
            push(mtime(&f), "Blocker gemeldet, Helfer wird gefragt", text(&v, "reason"), &mut events);
        }
        for f in files_for(&root.join("blockers/resolutions"), &task) {
            let v = read_json(&f).unwrap_or_default();
            let provider = text(&v, "provider").unwrap_or_else(|| "Helfer".into());
            add_helper(&format!("Rat: {}", provider_name(&provider)), &mut helpers);
            let detail = v.pointer("/proposal/diagnosis").and_then(Value::as_str).map(redact);
            push(mtime(&f), &format!("Rat von {} erhalten", provider_name(&provider)), detail, &mut events);
        }
        for f in files_for(&root.join("blockers/router-failed"), &task) {
            push(mtime(&f), "Helfer-Anfrage fehlgeschlagen", None, &mut events);
        }
        for f in files_for(&root.join("developer-results"), &task) {
            touched = true;
            let v = read_json(&f).unwrap_or_default();
            let status = text(&v, "status").unwrap_or_default();
            if v["model_calls"].as_u64().unwrap_or(0) > 0 {
                let on_server = text(&v, "model").map_or(false, |m| m == cfg.hard_model);
                let name = if on_server { "Server-Qwen" } else { "Qwen" };
                add_helper(&format!("{name} ({}x)", v["model_calls"]), &mut helpers);
            }
            if v["codex_fallback_calls"].as_u64().unwrap_or(0) > 0 {
                let failed = v.get("codex_fallback_error").map_or(false, |e| !e.is_null());
                add_helper(if failed { "Codex (Fehler)" } else { "Codex" }, &mut helpers);
            }
            if v["claude_fallback_calls"].as_u64().unwrap_or(0) > 0 {
                let failed = v.get("claude_fallback_error").map_or(false, |e| !e.is_null());
                add_helper(if failed { "Claude (Fehler)" } else { "Claude" }, &mut helpers);
            }
            let detail = text(&v, "reason").or_else(|| text(&v, "qwen_blocker_reason"));
            let phase = match status.as_str() {
                "BLOCKED" => "Patch blockiert".to_string(),
                "VERIFYING" => format!(
                    "Patch fertig ({}), Tests {}",
                    text(&v, "fallback_provider").map(|p| provider_name(&p)).unwrap_or_else(|| "Qwen".into()),
                    if v.pointer("/tests/returncode").and_then(Value::as_i64) == Some(0) { "grün" } else { "offen" }
                ),
                other => format!("Patch-Ergebnis {other}"),
            };
            push(mtime(&f), &phase, detail, &mut events);
        }
        for f in files_for(&root.join("acceptance-results"), &task) {
            let v = read_json(&f).unwrap_or_default();
            let at = v["at_unix_ms"].as_u64().map(|ms| ms / 1000).or_else(|| mtime(&f));
            push(at, &format!("Abnahme: {}", text(&v, "status").unwrap_or_default()), None, &mut events);
        }
        if touched {
            attempts += 1;
        }
    }
    let pr_body = cfg.state_dir.join(format!("runs/issue-{issue}-pr.md"));
    if let Ok(body) = fs::read_to_string(&pr_body) {
        if let Some(line) = body.lines().find(|l| l.starts_with("Implementation provider:")) {
            let provider = line.split(':').nth(1).unwrap_or("").trim();
            add_helper(&format!("Umsetzung: {}", provider_name(provider)), &mut helpers);
        }
        events.push(json!({"at": mtime(&pr_body), "phase": "PR erstellt", "detail": null, "place": "runs"}));
    }
    events.sort_by_key(|e| e["at"].as_u64().unwrap_or(0));
    let worktree = cfg.state_dir.join(format!("worktrees/issue-{issue}-qwen"));
    let started = events.first().and_then(|e| e["at"].as_u64());
    json!({
        "issue": issue,
        "attempts": attempts,
        "helpers": helpers,
        "events": events,
        "started_at": started,
        "worktree_created_at": created(&worktree),
        "worktree_exists": worktree.exists(),
    })
}

fn provider_name(raw: &str) -> String {
    match raw {
        "CODEX_CLI" => "Codex".into(),
        "CLAUDE_CLI" => "Claude".into(),
        "LOCAL_QWEN_OLLAMA" => "Qwen".into(),
        "OMNIROUTE" => "OmniRoute".into(),
        other => other.to_string(),
    }
}

/// Issue numbers that have a worktree or archived attempt on disk.
pub fn local_issue_numbers(cfg: &Config) -> Vec<u64> {
    let mut numbers = Vec::new();
    for dir in ["worktrees", "archive"] {
        if let Ok(entries) = fs::read_dir(cfg.state_dir.join(dir)) {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if let Some(n) = name.strip_prefix("issue-").and_then(|r| r.split('-').next()).and_then(|n| n.parse().ok()) {
                    if !numbers.contains(&n) {
                        numbers.push(n);
                    }
                }
            }
        }
    }
    numbers.sort_unstable();
    numbers
}

fn log_tail(path: &Path) -> Vec<String> {
    let Ok(mut file) = fs::File::open(path) else { return vec![] };
    let len = file.metadata().map(|m| m.len()).unwrap_or(0);
    let start = len.saturating_sub(LOG_TAIL_BYTES);
    if file.seek(SeekFrom::Start(start)).is_err() {
        return vec![];
    }
    let mut buf = Vec::new();
    let _ = file.read_to_end(&mut buf);
    let text = String::from_utf8_lossy(&buf);
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    if start > 0 && !lines.is_empty() {
        lines.remove(0);
    }
    lines
}

/// Every idle intake starts like this; the suffix says whether triage had anything left.
const IDLE_PREFIX: &str = "No eligible Mac Qwen issue";
/// `scripts/run_local_qwen_daemon.py` polls GitHub at most every 300 s when idle.
pub const INTAKE_INTERVAL_SECS: u64 = 300;

/// Summarises the stdout log: last intake result, last error and how long the
/// worker has been idle (the log carries no timestamps, so this is in polls).
pub fn log_summary(cfg: &Config) -> Value {
    let out = cfg.log_dir.join("local-first.out.log");
    let err = cfg.log_dir.join("local-first.err.log");
    let lines = log_tail(&out);
    let mut last_intake: Option<Value> = None;
    let mut last_error: Option<Value> = None;
    let mut idle_polls = 0u64;
    let mut counting_idle = true;
    let mut intakes_seen = 0u64;
    let mut last_triage: Option<Value> = None;
    for line in lines.iter().rev() {
        let Ok(record) = serde_json::from_str::<Value>(line) else { continue };
        if let Some(status) = record.get("TIM_GITHUB_INTAKE").and_then(Value::as_str) {
            let output = record["output"].as_str().unwrap_or("");
            if counting_idle && status == "DONE" && output.starts_with(IDLE_PREFIX) {
                idle_polls += 1;
            } else {
                counting_idle = false;
            }
            if last_triage.is_none() && output.starts_with("Triage: #") {
                last_triage = Some(json!({"text": redact(output), "intake_polls_since": intakes_seen}));
            }
            intakes_seen += 1;
            if last_intake.is_none() {
                last_intake = Some(json!({"status": status, "output": redact(output), "error": text(&record, "error")}));
            }
        }
        if last_error.is_none() {
            let error = text(&record, "error").or_else(|| text(&record, "blocker_reason")).or_else(|| text(&record, "error_type"));
            let blocked = record.as_object().map_or(false, |o| o.values().any(|v| v == "BLOCKED" || v == "SAFE_STOP"));
            if error.is_some() || blocked {
                // The log has no timestamps; intake polls since the error tell how old it is.
                let since = intakes_seen.saturating_sub(u64::from(record.get("TIM_GITHUB_INTAKE").is_some()));
                // The log has no clock; one idle poll is about INTAKE_INTERVAL_SECS.
                last_error = Some(json!({"text": error, "record": summarise(&record), "intake_polls_since": since,
                                         "age_estimate_secs": since * INTAKE_INTERVAL_SECS}));
            }
        }
        if last_intake.is_some() && last_error.is_some() && last_triage.is_some() && !counting_idle {
            break;
        }
    }
    let stderr_tail: Vec<String> = log_tail(&err).iter().rev().take(3).rev().map(|l| redact(l)).collect();
    json!({
        "last_intake": last_intake,
        "last_error": last_error,
        "last_triage": last_triage,
        "idle_polls": idle_polls,
        "intake_interval_secs": INTAKE_INTERVAL_SECS,
        "stdout_updated_at": mtime(&out),
        "stderr_updated_at": mtime(&err),
        "stderr_tail": stderr_tail,
    })
}

/// Triage bookkeeping from the worker's `issue-ledger.json`: when Claude last judged an
/// issue and how many judgements the rolling 24 h budget has used.
pub fn triage_ledger(cfg: &Config, now: u64) -> Value {
    let ledger = read_json(&cfg.state_dir.join("issue-ledger.json")).unwrap_or(Value::Null);
    let calls: Vec<f64> = ledger["triage_calls"].as_array().map_or(vec![], |a| a.iter().filter_map(Value::as_f64).collect());
    let last = calls.iter().copied().fold(None, |m: Option<f64>, t| Some(m.map_or(t, |m| m.max(t))));
    let day = calls.iter().filter(|t| **t >= now.saturating_sub(86_400) as f64).count();
    json!({"last_call_at": last.map(|t| t as u64), "calls_last_24h": day})
}

fn summarise(record: &Value) -> String {
    let Some(object) = record.as_object() else { return String::new() };
    let mut parts = Map::new();
    for (k, v) in object.iter().take(6) {
        parts.insert(k.clone(), v.clone());
    }
    redact(&Value::Object(parts).to_string())
}

// Read only the routing fields from a live process; never return its full environment.
fn process_routing(pid: u32) -> Value {
    let output = Command::new("/bin/ps").args(["eww", "-p", &pid.to_string(), "-o", "command="]).output();
    let Ok(output) = output else { return Value::Null };
    if !output.status.success() { return Value::Null; }
    routing_fields(&String::from_utf8_lossy(&output.stdout))
}

fn routing_fields(command: &str) -> Value {
    let mut fields = Map::new();
    for word in command.split_whitespace() {
        if let Some((key, value)) = word.split_once('=') {
            if ["TIM_QWEN_SERVER_RUN", "TIM_QWEN_HARD_RUN", "TIM_QWEN_SERVER_PREFERRED", "TIM_QWEN_SERVER_KEEP_WARM", "TIM_WORKER_CI_PAUSE", "OLLAMA_MODEL"].contains(&key) {
                fields.insert(key.into(), json!(redact(value)));
            }
        }
    }
    Value::Object(fields)
}

fn developer_from_processes(cfg: &Config, issue: u64, processes: &str) -> Value {
    let inbox = cfg.state_dir.join(format!("worktrees/issue-{issue}-qwen/.tim/local-first/developer-inbox/github-issue-{issue}.json"));
    for line in processes.lines() {
        let line = line.trim();
        let Some((pid, command)) = line.split_once(char::is_whitespace) else { continue };
        if command.contains("scripts/run_local_qwen_developer.py ") && command.contains(inbox.to_string_lossy().as_ref()) {
            if let Ok(pid) = pid.parse::<u32>() { return json!({"pid": pid}); }
        }
    }
    Value::Null
}

#[derive(Debug)]
struct Process {
    pid: u32,
    parent: u32,
    command: String,
}

fn parse_processes(raw: &str) -> Vec<Process> {
    raw.lines().filter_map(|line| {
        let mut words = line.trim().splitn(2, char::is_whitespace);
        let pid = words.next()?.parse().ok()?;
        let mut rest = words.next()?.trim().splitn(2, char::is_whitespace);
        Some(Process { pid, parent: rest.next()?.parse().ok()?, command: rest.next()?.trim().into() })
    }).collect()
}

fn descendant(process: &Process, root: u32, processes: &[Process]) -> bool {
    let mut parent = process.parent;
    for _ in 0..64 {
        if parent == root { return true; }
        let Some(next) = processes.iter().find(|p| p.pid == parent) else { return false };
        if next.parent == parent { return false; }
        parent = next.parent;
    }
    false
}

fn active_issue(cfg: &Config, worker_pid: u32, processes: &[Process]) -> Option<u64> {
    for process in processes.iter().filter(|p| descendant(p, worker_pid, processes)) {
        if let Some((_, tail)) = process.command.split_once("scripts/run_local_qwen_build_queue.py --task-id github-issue-") {
            if let Some(issue) = tail.split_whitespace().next().and_then(|v| v.parse().ok()) { return Some(issue); }
        }
        if process.command.contains("scripts/run_local_qwen_developer.py ") {
            let prefix = cfg.state_dir.join("worktrees").to_string_lossy().to_string() + "/issue-";
            if let Some((_, tail)) = process.command.split_once(&prefix) {
                if let Some(issue) = tail.split_once("-qwen/").and_then(|(n, _)| n.parse().ok()) { return Some(issue); }
            }
        }
    }
    None
}

fn active_developer(cfg: &Config, issue: u64, processes: &[Process]) -> Value {
    let raw = processes.iter().map(|p| format!("{} {}", p.pid, p.command)).collect::<Vec<_>>().join("\n");
    let mut developer = developer_from_processes(cfg, issue, &raw);
    if let Some(pid) = developer["pid"].as_u64() {
        let routing = process_routing(pid as u32);
        developer["backend"] = if routing["TIM_QWEN_SERVER_RUN"] == "1" || routing["TIM_QWEN_HARD_RUN"] == "1" {
            json!("server")
        } else if routing["OLLAMA_MODEL"].is_string() { json!("mac") } else { Value::Null };
        developer["model"] = routing["OLLAMA_MODEL"].clone();
        let children: Vec<&Process> = processes.iter().filter(|p| descendant(p, pid as u32, processes)).collect();
        developer["phase"] = json!(if children.iter().any(|p| p.command.contains("codex") && p.command.contains("exec")) {
            "Codex-Helfer läuft"
        } else if children.iter().any(|p| p.command.contains("claude")) {
            "Claude-Helfer läuft"
        } else if children.iter().any(|p| p.command.contains("pytest")) {
            "Tests laufen"
        } else { "Entwicklerprozess läuft; wartet auf Modell oder verarbeitet Antwort" });
    }
    developer
}

pub fn worker_state(cfg: &Config) -> Value {
    let agent = launch_agent(&cfg.worker_label);
    let raw = Command::new("/bin/ps").args(["-axo", "pid=,ppid=,command="]).output().ok()
        .filter(|o| o.status.success()).map(|o| String::from_utf8_lossy(&o.stdout).to_string());
    let processes = parse_processes(raw.as_deref().unwrap_or(""));
    let worker_pid = agent["pid"].as_u64().unwrap_or(0) as u32;
    let current_issue = if worker_pid > 0 { active_issue(cfg, worker_pid, &processes) } else { None };
    let routing = agent["pid"].as_u64().map(|pid| process_routing(pid as u32)).unwrap_or(Value::Null);
    let developer = current_issue.map(|issue| active_developer(cfg, issue, &processes)).unwrap_or(Value::Null);
    let paused_ci = current_issue.is_none() && agent["running"] == true && routing["TIM_WORKER_CI_PAUSE"] != "0"
        && processes.iter().any(|p| p.command.contains("/Runner.Worker"));
    json!({
        "routing": {"server_preferred": routing["TIM_QWEN_SERVER_PREFERRED"] == "1",
                    "keep_warm": routing["TIM_QWEN_SERVER_KEEP_WARM"] == "1"},
        "developer": developer,
        "agent": agent,
        "run_active": current_issue.is_some(),
        "process_observation_ok": raw.is_some(),
        "paused_ci": paused_ci,
        "current_issue": current_issue,
        "ollama": ollama(&cfg.ollama_url, &cfg.model),
        "server": {
            "tunnel": launch_agent(&cfg.tunnel_label),
            "url": cfg.hard_url,
            "ollama": server_model(&cfg.hard_url, &cfg.hard_model),
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn issue_evidence_does_not_access_the_protected_source_checkout() {
        let mut cfg = crate::Config::for_tests();
        cfg.worker_repo = PathBuf::from("/protected/Documents/source");
        cfg.state_dir = std::env::temp_dir().join(format!("mwd-evidence-{}", std::process::id()));
        let roots = evidence_roots(&cfg, 242);
        assert_eq!(roots.len(), 1);
        assert!(roots.iter().all(|(_, p)| p.starts_with(&cfg.state_dir)));
        assert!(roots[0].1.ends_with("worktrees/issue-242-qwen/.tim/local-first"));
    }

    #[test]
    fn current_issue_requires_a_live_worker_descendant_not_an_old_worktree() {
        let cfg = crate::Config::for_tests();
        let idle = parse_processes("10 1 python daemon\n20 10 python scripts/run_mac_qwen_issue.py --action intake\n30 1 python scripts/run_local_qwen_build_queue.py --task-id github-issue-999");
        assert_eq!(active_issue(&cfg, 10, &idle), None);
        let busy = parse_processes("10 1 python daemon\n20 10 python intake\n30 20 python scripts/run_local_qwen_build_queue.py --task-id github-issue-242");
        assert_eq!(active_issue(&cfg, 10, &busy), Some(242));
        assert_eq!(active_issue(&cfg, 99, &busy), None);
    }

    #[test]
    fn complete_http_reply_does_not_wait_for_connection_close() {
        use std::io::Write;
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let (release, hold) = std::sync::mpsc::channel::<()>();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            let mut request = [0u8; 1024];
            socket.read(&mut request).unwrap();
            socket.write_all(b"HTTP/1.0 200 OK\r\nContent-Length: 13\r\n\r\n{\"models\":[]}").unwrap();
            let _ = hold.recv_timeout(std::time::Duration::from_secs(5));
        });
        let response = http_get(&url, "/api/ps");
        release.send(()).unwrap();
        server.join().unwrap();
        assert_eq!(response.as_deref(), Some(r#"{"models":[]}"#));
    }

    #[test]
    fn failed_loaded_model_probe_is_unknown_not_cold() {
        use std::io::Write;
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let server = std::thread::spawn(move || {
            for body in [r#"{"models":[{"name":"qwen3-coder:30b"}]}"#, "unavailable"] {
                let (mut socket, _) = listener.accept().unwrap();
                let mut request = [0u8; 1024];
                socket.read(&mut request).unwrap();
                write!(socket, "HTTP/1.0 200 OK\r\nContent-Length: {}\r\n\r\n{}", body.len(), body).unwrap();
            }
        });
        let state = server_model(&url, "qwen3-coder:30b");
        server.join().unwrap();
        assert_eq!(state["reachable"], json!(true));
        assert_eq!(state["model_installed"], json!(true));
        assert_eq!(state["warm"], Value::Null);
    }

    #[test]
    fn routing_is_whitelisted_and_uses_exact_keys() {
        let fields = routing_fields("python TIM_QWEN_SERVER_RUN=1 OLLAMA_MODEL=qwen3-coder:30b GH_TOKEN=secret NOT_TIM_QWEN_SERVER_RUN=0");
        assert_eq!(fields, json!({"TIM_QWEN_SERVER_RUN":"1", "OLLAMA_MODEL":"qwen3-coder:30b"}));
        assert_eq!(routing_fields("python"), json!({}));
    }

    #[test]
    fn developer_must_match_the_current_issue_worktree() {
        let mut cfg = crate::Config::for_tests();
        cfg.state_dir = PathBuf::from("/tmp/TIM Worker");
        let processes = "12 python scripts/run_local_qwen_developer.py /tmp/TIM Worker/worktrees/issue-241-qwen/.tim/local-first/developer-inbox/github-issue-241.json\n13 python scripts/run_local_qwen_developer.py /tmp/TIM Worker/worktrees/issue-242-qwen/.tim/local-first/developer-inbox/github-issue-242.json";
        assert_eq!(developer_from_processes(&cfg, 242, processes), json!({"pid":13}));
        assert_eq!(developer_from_processes(&cfg, 243, processes), Value::Null);
    }

    #[test]
    fn redacts_tokens_and_assignments() {
        let out = redact("login ok gho_abc123 and token=xyz and fine");
        assert!(!out.contains("gho_abc123"));
        assert!(!out.contains("xyz"));
        assert!(out.contains("fine"));
    }

    #[test]
    fn reads_triage_ledger() {
        let dir = std::env::temp_dir().join(format!("mwd-ledger-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("issue-ledger.json"), r#"{"issues":{},"triage_calls":[1000.5,90000.0,95000.2]}"#).unwrap();
        let mut cfg = crate::Config::for_tests();
        cfg.state_dir = dir.clone();
        let t = triage_ledger(&cfg, 100_000);
        assert_eq!(t["last_call_at"], json!(95000));
        assert_eq!(t["calls_last_24h"], json!(2));
        fs::remove_dir_all(dir).unwrap();
    }

    /// Answers each connection like Ollama would for `/api/tags` and `/api/ps`.
    fn fake_ollama(loaded: &'static str) -> String {
        use std::io::{BufRead, BufReader, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        std::thread::spawn(move || {
            for mut stream in listener.incoming().flatten() {
                // Read the whole request first; closing with unread bytes would reset the connection.
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                let mut rest = String::new();
                while reader.read_line(&mut rest).unwrap_or(0) > 0 && !rest.ends_with("\r\n\r\n") {}
                let body = if line.contains("/api/ps") { loaded } else { r#"{"models":[{"name":"qwen3-coder:30b"}]}"# };
                let _ = write!(stream, "HTTP/1.0 200 OK\r\n\r\n{body}");
            }
        });
        url
    }

    #[test]
    fn server_model_warm_and_cold() {
        let warm = server_model(&fake_ollama(r#"{"models":[{"name":"qwen3-coder:30b","expires_at":"2026-10-15T01:30:00Z","size":1}]}"#), "qwen3-coder:30b");
        assert_eq!(warm["reachable"], json!(true));
        assert_eq!(warm["model_installed"], json!(true));
        assert_eq!(warm["warm"], json!(true));
        assert_eq!(warm["expires_at"], json!("2026-10-15T01:30:00Z"));
        let cold = server_model(&fake_ollama(r#"{"models":[]}"#), "qwen3-coder:30b");
        assert_eq!(cold["warm"], json!(false));
        let down = server_model("http://127.0.0.1:1", "qwen3-coder:30b");
        assert_eq!(down["reachable"], json!(false));
    }

    #[test]
    fn keeps_plain_text() {
        assert_eq!(redact("issue worktree or branch already exists"), "issue worktree or branch already exists");
    }

    #[test]
    fn parses_lock_formats() {
        let dir = std::env::temp_dir().join(format!("mwd-lock-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("a"), "pid=42\n").unwrap();
        fs::write(dir.join("b"), "43").unwrap();
        assert_eq!(lock_pid(&dir.join("a")), Some(42));
        assert_eq!(lock_pid(&dir.join("b")), Some(43));
        fs::remove_dir_all(dir).unwrap();
    }
}
