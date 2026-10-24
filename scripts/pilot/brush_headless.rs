// Headless entry point for the pinned Brush v0.3.0 process pipeline.
// GPU math is unchanged; the task-owned CubeCL patch uses synchronized system
// timing for autotuning instead of the failing Vulkan timestamp measurements.
use brush_cli::Cli;
use clap::Parser;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args = Cli::parse().validate()?;
    anyhow::ensure!(!args.with_viewer, "This local worker is headless");
    env_logger::builder().target(env_logger::Target::Stdout).init();
    let source = args.source.ok_or_else(|| anyhow::anyhow!("Source required"))?;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let _ = sender.send(args.process.clone());
    let device = brush_render::burn_init_setup().await;
    let stream = brush_process::process::process_stream(source, receiver, device);
    brush_cli::process_ui(stream, args.process).await
}
