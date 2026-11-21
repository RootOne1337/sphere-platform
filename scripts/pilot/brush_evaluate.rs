// Offline reference-view evaluation for the pinned Brush v0.3.0 backend.
// No training, inputs, credentials, model changes or network access.
use std::{path::PathBuf, sync::Arc};
use brush_dataset::{config::LoadDataseConfig, load_dataset};
use brush_render::burn_init_setup;
use brush_serde::load_splat_from_ply;
use brush_train::eval::eval_stats;
use brush_vfs::DataSource;
use serde_json::json;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    anyhow::ensure!(args.len() == 4, "Expected dataset, PLY, exclusive output directory");
    let output = PathBuf::from(&args[3]);
    std::fs::create_dir(&output)?;
    env_logger::builder().target(env_logger::Target::Stdout).init();
    let device = burn_init_setup().await;
    let config = LoadDataseConfig { max_frames: None, max_resolution: 960,
        eval_split_every: None, subsample_frames: None, subsample_points: None };
    let vfs = Arc::new(DataSource::Path(args[1].clone()).into_vfs().await?);
    let (_, dataset) = load_dataset(vfs, &config, &device).await?;
    let splats = load_splat_from_ply(tokio::fs::File::open(&args[2]).await?, None, device.clone()).await?.splats;
    let mut results = vec![];
    let n = dataset.train.views.len();
    anyhow::ensure!(n >= 3, "At least three reference views required");
    for index in (0..9).map(|i| i * (n - 1) / 8).collect::<std::collections::BTreeSet<_>>() {
        let view = &dataset.train.views[index];
        let sample = eval_stats(&splats, &view.camera, view.image.load().await?, view.image.is_masked(), &device)?;
        let psnr = sample.psnr.clone().into_scalar_async().await;
        let ssim = sample.ssim.clone().into_scalar_async().await;
        let dims = sample.rendered.dims();
        let data = sample.rendered.into_data_async().await.into_vec::<f32>()
            .map_err(|error| anyhow::anyhow!("Render buffer: {error:?}"))?;
        let img: image::DynamicImage = image::Rgb32FImage::from_raw(dims[1] as u32, dims[0] as u32, data)
            .ok_or_else(|| anyhow::anyhow!("Render dimensions mismatch"))?.into();
        let stem = view.image.path.file_stem().unwrap().to_string_lossy();
        img.into_rgb8().save(output.join(format!("{stem}-render.png")))?;
        sample.gt_img.save(output.join(format!("{stem}-source.png")))?;
        println!("View {stem}: PSNR {psnr}, SSIM {ssim}");
        results.push(json!({"image": view.image.path, "psnr": psnr, "ssim": ssim}));
    }
    std::fs::write(output.join("metrics.json"), serde_json::to_vec_pretty(&json!({
        "schema": "sphere-reference-render-evaluation-v1", "views": results,
        "resolution_limit": 960, "training": false, "held_out": false
    }))?)?;
    Ok(())
}
