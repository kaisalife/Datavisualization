use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

/// JS -> Rust 桥接服务器
/// JS 通过 fetch('http://127.0.0.1:PORT/api', {method:'POST', body:JSON.stringify({action, data})}) 发送消息
/// Rust 接收后通过 channel 发送给主组件
pub struct BridgeServer {
    pub port: u16,
    shutdown: Arc<tokio::sync::Notify>,
}

impl BridgeServer {
    /// 启动桥接服务器，返回端口
    pub async fn start(tx: tokio::sync::mpsc::UnboundedSender<BridgeMessage>) -> std::io::Result<Self> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let port = listener.local_addr()?.port();
        let shutdown = Arc::new(tokio::sync::Notify::new());

        println!("[Bridge] HTTP 服务器启动在 127.0.0.1:{}", port);

        let shutdown_clone = shutdown.clone();
        tokio::spawn(async move {
            loop {
                tokio::select! {
                    accept_result = listener.accept() => {
                        let (mut stream, _) = match accept_result {
                            Ok(s) => s,
                            Err(_) => continue,
                        };

                        // 读取 HTTP 请求（循环读至读满 Content-Length，避免大请求体截断）
                        let mut buf: Vec<u8> = Vec::new();
                        let mut header_end: Option<usize> = None;
                        loop {
                            let mut chunk = vec![0u8; 8192];
                            let n = match stream.read(&mut chunk).await {
                                Ok(n) if n > 0 => n,
                                _ => break,
                            };
                            buf.extend_from_slice(&chunk[..n]);
                            if header_end.is_none() {
                                header_end = find_header_end(&buf);
                            }
                            if let Some(hend) = header_end {
                                let clen = content_length(&buf[..hend]);
                                let body_have = buf.len() - (hend + 4);
                                if body_have >= clen {
                                    break;
                                }
                            }
                            // 上限 16MB 防滥用
                            if buf.len() > 16 * 1024 * 1024 {
                                break;
                            }
                        }

                        // 提取 body（按 Content-Length 截取，避免含尾部/分片噪声）
                        let body = match header_end {
                            Some(hend) => {
                                let clen = content_length(&buf[..hend]);
                                let start = hend + 4;
                                let end = (start + clen).min(buf.len());
                                std::str::from_utf8(&buf[start..end]).unwrap_or("")
                            }
                            None => "",
                        };

                        // 解析 JSON
                        if !body.is_empty() {
                            if let Ok(json) = serde_json::from_str::<serde_json::Value>(body) {
                                let action = json.get("action")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let data = json.get("data")
                                    .cloned()
                                    .unwrap_or(serde_json::Value::Null);

                                println!("[Bridge] 收到 JS 消息: action={}", action);

                                let msg = BridgeMessage { action, data };
                                if tx.send(msg).is_err() {
                                    println!("[Bridge] 通道已关闭，停止服务器");
                                    break;
                                }
                            }
                        }

                        // 返回 CORS 友好的 HTTP 响应
                        let response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: POST, OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}";
                        let _ = stream.write_all(response.as_bytes()).await;
                        let _ = stream.flush().await;
                    }
                    _ = shutdown_clone.notified() => {
                        println!("[Bridge] 服务器关闭");
                        break;
                    }
                }
            }
        });

        Ok(Self { port, shutdown })
    }

    /// 停止服务器
    pub fn shutdown(&self) {
        self.shutdown.notify_waiters();
    }
}

/// 从 JS 桥接过来的消息
#[derive(Debug, Clone)]
pub struct BridgeMessage {
    pub action: String,
    pub data: serde_json::Value,
}

/// 在缓冲区中查找 HTTP 头部结束位置（\r\n\r\n）
fn find_header_end(buf: &[u8]) -> Option<usize> {
    buf.windows(4).position(|w| w == b"\r\n\r\n")
}

/// 从 HTTP 头部解析 Content-Length
fn content_length(headers: &[u8]) -> usize {
    let s = std::str::from_utf8(headers).unwrap_or("");
    for line in s.split("\r\n") {
        let lower = line.to_ascii_lowercase();
        if let Some(rest) = lower.strip_prefix("content-length:") {
            if let Ok(n) = rest.trim().parse::<usize>() {
                return n;
            }
        }
    }
    0
}
