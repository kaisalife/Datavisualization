use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::mpsc::UnboundedSender;

/// JS -> Rust 桥接服务器
/// JS 通过 fetch('http://127.0.0.1:PORT/api', {method:'POST', body:JSON.stringify({action, data})}) 发送消息
/// Rust 接收后通过 channel 发送给主组件
pub struct BridgeServer {
    pub port: u16,
    shutdown: Arc<tokio::sync::Notify>,
}

impl BridgeServer {
    /// 启动桥接服务器，返回端口
    pub async fn start(tx: UnboundedSender<BridgeMessage>) -> std::io::Result<Self> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let port = listener.local_addr()?.port();
        let shutdown = Arc::new(tokio::sync::Notify::new());

        println!("[Bridge] HTTP 服务器启动在 127.0.0.1:{}", port);

        let shutdown_clone = shutdown.clone();
        tokio::spawn(async move {
            loop {
                tokio::select! {
                    accept_result = listener.accept() => {
                        let (stream, _) = match accept_result {
                            Ok(s) => s,
                            Err(_) => continue,
                        };
                        // 每个连接独立处理：慢连接/半开连接不会阻塞后续桥接请求。
                        // 之前的实现直接在 accept 循环里同步读到完整请求体，一个不发数据的
                        // 连接就能把整个 JS->Rust 通道卡死。
                        let tx = tx.clone();
                        tokio::spawn(async move {
                            handle_connection(stream, tx).await;
                        });
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

/// 处理单个桥接连接：读满 Content-Length、解析 JSON、入队、返回固定响应。
async fn handle_connection(mut stream: TcpStream, tx: UnboundedSender<BridgeMessage>) {
    // 读取 HTTP 请求（循环读至读满 Content-Length，避免大请求体截断）
    let mut buf: Vec<u8> = Vec::new();
    let mut header_end: Option<usize> = None;
    loop {
        let mut chunk = vec![0u8; 8192];
        // 30s 内没有任何新数据就放弃该连接，防止半开连接长期占用任务
        let read = tokio::time::timeout(Duration::from_secs(30), stream.read(&mut chunk)).await;
        let n = match read {
            Ok(Ok(n)) if n > 0 => n,
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
            let action = json
                .get("action")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let data = json
                .get("data")
                .cloned()
                .unwrap_or(serde_json::Value::Null);

            println!("[Bridge] 收到 JS 消息: action={}", action);

            let msg = BridgeMessage { action, data };
            if tx.send(msg).is_err() {
                println!("[Bridge] 通道已关闭，忽略该消息");
            }
        }
    }

    // 返回 CORS 友好的 HTTP 响应
    let response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: POST, OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}";
    let _ = stream.write_all(response.as_bytes()).await;
    let _ = stream.flush().await;
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

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    /// 半开连接（连上但不发数据）不能阻塞其它桥接请求。
    /// 旧实现把读请求体放在 accept 循环里，遇到这种连接整个 JS->Rust 通道会卡死。
    #[tokio::test]
    async fn silent_connection_does_not_block_bridge() {
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
        let server = BridgeServer::start(tx).await.unwrap();
        let addr = format!("127.0.0.1:{}", server.port);

        let _silent = TcpStream::connect(&addr).await.unwrap();

        let mut client = TcpStream::connect(&addr).await.unwrap();
        let body = "{\"action\":\"ping\",\"data\":{}}";
        let req = format!(
            "POST /api HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        client.write_all(req.as_bytes()).await.unwrap();

        let mut resp = Vec::new();
        tokio::time::timeout(Duration::from_secs(3), client.read_to_end(&mut resp))
            .await
            .expect("正常请求被半开连接阻塞")
            .unwrap();
        let text = String::from_utf8_lossy(&resp);
        assert!(text.starts_with("HTTP/1.1 200 OK"), "unexpected response: {text}");

        let msg = tokio::time::timeout(Duration::from_secs(3), rx.recv())
            .await
            .expect("消息未入队")
            .expect("通道已关闭");
        assert_eq!(msg.action, "ping");

        server.shutdown();
    }
}
