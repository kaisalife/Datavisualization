use serde::{Deserialize, Serialize};
use crate::api;

/// 应用主模式：对话或代码补全
#[derive(Debug, PartialEq, Clone, Copy)]
pub(crate) enum AppMode {
    Chat,
    CodeCompletion,
}

/// 应用设置（可序列化到 settings.json）
#[derive(Clone, Serialize, Deserialize)]
pub(crate) struct AppSettings {
    pub(crate) backend_url: String,
    pub(crate) api_key: String,
    pub(crate) model_url: Option<String>,
    pub(crate) model_type: Option<String>,
    pub(crate) model_api_key: Option<String>,
    /// 已保存的模型配置列表（多模型 + 启用）
    #[serde(default)]
    pub(crate) model_configs: Vec<api::types::ModelConfig>,
    pub(crate) mcp_prompt: Option<String>,
    pub(crate) skill_prompt: Option<String>,
    /// 已保存的数据库配置列表
    #[serde(default)]
    pub(crate) db_configs: Vec<api::types::DbConfig>,
}

impl AppSettings {
    /// 获取当前启用的模型配置；若不存在则回退到旧版单模型字段
    pub(crate) fn active_model_config(&self) -> Option<api::types::ModelConfig> {
        if let Some(cfg) = self.model_configs.iter().find(|m| m.enabled).cloned() {
            return Some(cfg);
        }
        // 兼容旧配置：从单模型字段合成一个临时配置
        let model_type = self.model_type.clone()?;
        let model_url = self.model_url.clone()?;
        let model_api_key = self.model_api_key.clone().unwrap_or_default();
        Some(api::types::ModelConfig {
            id: "legacy".to_string(),
            name: model_type.clone(),
            model_type,
            model_url,
            model_api_key,
            enabled: true,
        })
    }
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            backend_url: std::env::var("BACKEND_URL")
                .unwrap_or_else(|_| "http://localhost:5000".to_string()),
            api_key: std::env::var("API_KEY").unwrap_or_default(),
            model_url: std::env::var("MODEL_URL").ok(),
            model_type: std::env::var("MODEL_TYPE").ok(),
            model_api_key: std::env::var("MODEL_API_KEY").ok(),
            model_configs: Vec::new(),
            mcp_prompt: std::env::var("MCP_PROMPT").ok(),
            skill_prompt: std::env::var("SKILL_PROMPT").ok(),
            db_configs: Vec::new(),
        }
    }
}

impl AppSettings {
    /// 设置文件路径：定位 front-winui 项目根（含 Cargo.toml 的目录），settings.json 放此处。
    /// 相对路径、跟随项目；cargo build/clean 只动 target/，不碰项目根，配置不会因编译丢失。
    pub(crate) fn file_path() -> Option<std::path::PathBuf> {
        let exe = std::env::current_exe().ok()?;
        let exe_dir = exe.parent()?;
        // 从 exe 目录往上找 Cargo.toml，定位项目根
        let mut dir = exe_dir.to_path_buf();
        loop {
            if dir.join("Cargo.toml").exists() {
                return Some(dir.join("settings.json"));
            }
            match dir.parent() {
                Some(p) => dir = p.to_path_buf(),
                None => break,
            }
        }
        // 回退：exe 同级目录
        Some(exe_dir.join("settings.json"))
    }

    /// 旧路径（exe 同级目录，即 target/.../settings.json），用于一次性迁移到项目根
    fn legacy_file_path() -> Option<std::path::PathBuf> {
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|d| d.join("settings.json")))
    }

    pub(crate) fn load() -> Self {
        if let Some(path) = Self::file_path() {
            // 新路径存在则直接读
            if path.exists() {
                if let Ok(content) = std::fs::read_to_string(&path) {
                    if let Ok(settings) = serde_json::from_str::<AppSettings>(&content) {
                        return settings;
                    }
                }
            }
            // 迁移：新路径不存在时，从旧路径（exe 同级）复制过来，避免老用户配置丢失
            if !path.exists() {
                if let Some(old) = Self::legacy_file_path() {
                    if old.exists() && old != path {
                        if std::fs::copy(&old, &path).is_ok() {
                            if let Ok(content) = std::fs::read_to_string(&path) {
                                if let Ok(settings) = serde_json::from_str::<AppSettings>(&content) {
                                    return settings;
                                }
                            }
                        }
                    }
                }
            }
        }
        Self::default()
    }

    pub(crate) fn save(&self) -> std::result::Result<(), String> {
        let path = Self::file_path().ok_or_else(|| "无法获取 exe 路径".to_string())?;
        let json = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        std::fs::write(&path, json).map_err(|e| e.to_string())
    }

    pub(crate) fn backend_display(&self) -> String {
        self.backend_url
            .strip_prefix("http://")
            .or_else(|| self.backend_url.strip_prefix("https://"))
            .unwrap_or(&self.backend_url)
            .to_string()
    }
}
