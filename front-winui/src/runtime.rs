use std::sync::OnceLock;
use tokio::runtime::Runtime;

/// 全局 tokio 运行时（用 OnceLock 保证只初始化一次）
///
/// winio 使用 compio 运行时，无法直接 .await tokio future。
/// 在单独线程中通过 handle.block_on 执行 API 调用，用 sender.post 回传结果。
static TOKIO_RT: OnceLock<Runtime> = OnceLock::new();

/// 获取全局 tokio 运行时的 Handle
pub(crate) fn tokio_handle() -> tokio::runtime::Handle {
    TOKIO_RT
        .get_or_init(|| Runtime::new().expect("无法创建 tokio 运行时"))
        .handle()
        .clone()
}
