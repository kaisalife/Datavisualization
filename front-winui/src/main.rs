#[cfg(not(target_os = "android"))]
fn main() -> Result<(), main::Error> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();
    use main::MainModel;
    use winio::prelude::*;

    let app = App::builder().name("rs.datavisual.winui").build()?;
    app.block_on(MainModel::run(()))
}
