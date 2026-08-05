mod api;
mod runtime;
mod state;
mod messages;
mod model;
mod helpers;
mod component;
mod handlers;
mod ui;
mod bridge;

#[derive(Debug)]
pub struct Error(pub anyhow::Error);
impl From<anyhow::Error> for Error {
    fn from(e: anyhow::Error) -> Self {
        Self(e)
    }
}
impl From<winio::Error> for Error {
    fn from(e: winio::Error) -> Self {
        Self(anyhow::anyhow!("{}", e))
    }
}

pub use model::MainModel;
