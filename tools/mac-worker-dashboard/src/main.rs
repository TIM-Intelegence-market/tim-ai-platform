//! Read-only dashboard for the Mac Qwen issue worker (`com.tim.local-qwen-worker`).
//!
//! Serves one page and `/api/status` on 127.0.0.1 only. It reads the worker's
//! LaunchAgent state, locks, worktrees, run evidence and log, plus GitHub issue
//! and PR lists through `gh`. It never writes files, labels, issues or PRs.

mod github;
mod local;

use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const PAGE: &str = include_str!("index.html");

pub struct Config {
    pub port: u16,
    pub worker_repo: PathBuf,
    pub state_dir: PathBuf,
    pub log_dir: PathBuf,
    pub repo: String,
    pub worker_login: String,
    pub worker_label: String,
    pub gh: String,
    pub ollama_url: String,
    pub model: String,
    pub hard_url: String,
    pub hard_model: String,
    pub tunnel_label: String,
}

impl Config {
    fn defaults(home: PathBuf) -> Config {
        Config {
            port: 8767,
            worker_repo: home.join("Documents/TIM/mac-issue-worker"),
            state_dir: home.join("Library/Application Support/TIM Mac Issue Worker"),
            log_dir: home.join("Library/Logs/TIM"),
            repo: "TIM-Intelegence-market/tim-ai-platform".into(),
            worker_login: "apoman74-art".into(),
            worker_label: "com.tim.local-qwen-worker".into(),
            gh: "/opt/homebrew/bin/gh".into(),
            ollama_url: "http://127.0.0.1:11434".into(),
            model: "qwen3.5:9b".into(),
            hard_url: "http://127.0.0.1:11435".into(),
            hard_model: "qwen3-coder:30b".into(),
            tunnel_label: "com.tim.server-ollama-tunnel".into(),
        }
    }

    #[cfg(test)]
    pub fn for_tests() -> Config {
        Config::defaults(std::env::temp_dir())
    }

    fn from_args() -> Result<Config, String> {
        let home = PathBuf::from(std::env::var("HOME").map_err(|_| "HOME fehlt")?);
        let mut cfg = Config::defaults(home);
        let args: Vec<String> = std::env::args().skip(1).collect();
        let mut it = args.iter();
        while let Some(flag) = it.next() {
            let value = it.next().ok_or_else(|| format!("{flag} braucht einen Wert"))?.clone();
            match flag.as_str() {
                "--port" => cfg.port = value.parse().map_err(|_| "ungültiger Port")?,
                "--worker-repo" => cfg.worker_repo = value.into(),
                "--state-dir" => cfg.state_dir = value.into(),
                "--log-dir" => cfg.log_dir = value.into(),
                "--repo" => cfg.repo = value,
                "--worker-login" => cfg.worker_login = value,
                "--worker-label" => cfg.worker_label = value,
                "--gh" => cfg.gh = value,
                "--ollama-url" => cfg.ollama_url = value,
                "--model" => cfg.model = value,
                "--hard-url" => cfg.hard_url = value,
                "--hard-model" => cfg.hard_model = value,
                "--tunnel-label" => cfg.tunnel_label = value,
                other => return Err(format!("unbekannte Option {other}")),
            }
        }
        Ok(cfg)
    }
}

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn status(cfg: &Config, gh: Value) -> Value {
    let worker = local::worker_state(cfg);
    let log = local::log_summary(cfg);
    let prs: Vec<Value> = gh["worker_prs"].as_array().cloned().unwrap_or_default();
    // A merged or still open PR settles the issue; a closed one puts it back in the queue.
    let pr_issues: Vec<u64> = prs
        .iter()
        .filter(|p| p["state"] == "OPEN" || p["state"] == "MERGED")
        .filter_map(|p| p["issue"].as_u64())
        .collect();
    let current_issue = worker["current_issue"].as_u64();

    let current = current_issue.map(|n| {
        let mut run = local::issue_runs(cfg, n);
        run["phase"] = run["events"].as_array().and_then(|e| e.last()).map_or(json!("Worktree angelegt"), |e| e["phase"].clone());
        run
    });

    let done: Vec<Value> = prs
        .iter()
        .filter(|pr| Some(pr["issue"].as_u64().unwrap_or(0)) != current_issue || pr["state"] != "OPEN")
        .map(|pr| {
            let run = local::issue_runs(cfg, pr["issue"].as_u64().unwrap_or(0));
            json!({
                "issue": pr["issue"], "pr_number": pr["number"], "pr_url": pr["url"], "title": pr["title"],
                "state": pr["state"], "pr_created_at": pr["createdAt"], "merged_at": pr["mergedAt"],
                "closed_at": pr["closedAt"], "run_started_at": run["worktree_created_at"].as_u64().or(run["started_at"].as_u64()),
                "helpers": run["helpers"], "attempts": run["attempts"], "events": run["events"],
            })
        })
        .collect();

    // Once GitHub answered, leftovers of issues that are no longer open are not "stalled".
    let open_numbers: Option<Vec<u64>> = (gh["ok"] == json!(true))
        .then(|| gh["open_issues"].as_array().map(|a| a.iter().filter_map(|i| i["number"].as_u64()).collect()))
        .flatten();
    let stalled: Vec<Value> = local::local_issue_numbers(cfg)
        .into_iter()
        .filter(|n| !pr_issues.contains(n) && Some(*n) != current_issue)
        .filter(|n| open_numbers.as_ref().map_or(true, |open| open.contains(n)))
        .map(|n| local::issue_runs(cfg, n))
        .collect();

    let open: Vec<Value> = gh["open_issues"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|i| !pr_issues.contains(&i["number"].as_u64().unwrap_or(0)) || i["number"].as_u64() == current_issue)
        .collect();

    json!({
        "generated_at": now(),
        "worker": worker,
        "current": current,
        "stalled": stalled,
        "log": log,
        "triage": local::triage_ledger(cfg, now()),
        "open": open,
        "done": done,
        "github": {"ok": gh["ok"], "error": gh["error"], "loading": gh["loading"]},
    })
}

fn respond(stream: &mut TcpStream, code: &str, kind: &str, body: &[u8]) {
    let head = format!(
        "HTTP/1.1 {code}\r\nContent-Type: {kind}\r\nContent-Length: {}\r\nCache-Control: no-store\r\n\
         X-Content-Type-Options: nosniff\r\nX-Frame-Options: DENY\r\n\
         Content-Security-Policy: default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'\r\n\
         Connection: close\r\n\r\n",
        body.len()
    );
    let _ = stream.write_all(head.as_bytes());
    let _ = stream.write_all(body);
}

/// Accepts only local Host headers so a foreign page cannot read the API via DNS rebinding.
fn host_allowed(host: &str, port: u16) -> bool {
    [format!("127.0.0.1:{port}"), format!("localhost:{port}")].iter().any(|h| h == host)
}

fn handle(mut stream: TcpStream, cfg: &Arc<Config>, cache: &github::Cache) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let mut reader = BufReader::new(match stream.try_clone() {
        Ok(s) => s,
        Err(_) => return,
    });
    let mut request_line = String::new();
    if reader.read_line(&mut request_line).is_err() {
        return;
    }
    let mut host = String::new();
    for _ in 0..100 {
        let mut line = String::new();
        if reader.read_line(&mut line).unwrap_or(0) == 0 || line == "\r\n" || line == "\n" {
            break;
        }
        if let Some((name, value)) = line.split_once(':') {
            if name.eq_ignore_ascii_case("host") {
                host = value.trim().to_string();
            }
        }
    }
    let mut parts = request_line.split_whitespace();
    let (method, path) = (parts.next().unwrap_or(""), parts.next().unwrap_or(""));
    if !host_allowed(&host, cfg.port) {
        return respond(&mut stream, "421 Misdirected Request", "text/plain", b"local only");
    }
    if method != "GET" {
        return respond(&mut stream, "405 Method Not Allowed", "text/plain", b"read only");
    }
    match path {
        "/" => respond(&mut stream, "200 OK", "text/html; charset=utf-8", PAGE.as_bytes()),
        "/api/status" => {
            let body = status(cfg, cache.get(cfg)).to_string();
            respond(&mut stream, "200 OK", "application/json", body.as_bytes())
        }
        _ => respond(&mut stream, "404 Not Found", "text/plain", b"not found"),
    }
}

fn main() {
    let cfg = match Config::from_args() {
        Ok(cfg) => Arc::new(cfg),
        Err(e) => {
            eprintln!("mac-worker-dashboard: {e}");
            std::process::exit(2);
        }
    };
    if std::env::var("MWD_PRINT_STATUS").is_ok() {
        println!("{}", serde_json::to_string_pretty(&status(&cfg, github::Cache::fetch_now(&cfg))).unwrap_or_default());
        return;
    }
    let listener = match TcpListener::bind(("127.0.0.1", cfg.port)) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("mac-worker-dashboard: Port {} nicht verfügbar: {}", cfg.port, e.kind());
            std::process::exit(1);
        }
    };
    println!("Mac-Worker-Dashboard: http://127.0.0.1:{}", cfg.port);
    let cache = Arc::new(github::Cache::new());
    for stream in listener.incoming().flatten() {
        let (cfg, cache) = (Arc::clone(&cfg), Arc::clone(&cache));
        std::thread::spawn(move || handle(stream, &cfg, &cache));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_local_hosts() {
        assert!(host_allowed("127.0.0.1:8767", 8767));
        assert!(host_allowed("localhost:8767", 8767));
        assert!(!host_allowed("evil.example:8767", 8767));
        assert!(!host_allowed("127.0.0.1:9999", 8767));
    }
}
