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

                        // 读取 HTTP 请求
                        let mut buf = vec![0u8; 65536];
                        let n = match stream.read(&mut buf).await {
                            Ok(n) if n > 0 => n,
                            _ => continue,
                        };

                        let request = String::from_utf8_lossy(&buf[..n]).to_string();

                        // 提取 body（简单的 HTTP 解析）
                        let body = if let Some(pos) = request.find("\r\n\r\n") {
                            &request[pos + 4..]
                        } else {
                            ""
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
