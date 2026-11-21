use sa_mod::game::{
    GameLimit, GameOption, set_frame_limit, set_hud_visible, set_limit, set_option,
};
use sa_mod::{Event, Mod, event_kind, events, state};

#[derive(Default)]
struct RouteStart {
    last_sample: u32,
}

impl Mod for RouteStart {
    fn init(&mut self) -> Result<(), String> {
        for option in [
            GameOption::StartScreens,
            GameOption::HelpMessages,
            GameOption::ZoneNames,
            GameOption::VehicleNameOnHud,
            GameOption::VitalStatsOnHud,
        ] {
            set_option(option, false).map_err(|e| format!("display option {option:?}: {e:?}"))?;
        }
        #[cfg(feature = "full-world")]
        for (limit, count) in [
            (GameLimit::Matrices, 32768),
            (GameLimit::Buildings, 32767),
            (GameLimit::Dummies, 12000),
            (GameLimit::ColModels, 20000),
            (GameLimit::PtrNodesSingle, 400000),
        ] {
            set_limit(limit, count).map_err(|e| format!("world pool {limit:?}: {e:?}"))?;
        }
        set_frame_limit(30).map_err(|e| format!("frame limit: {e:?}"))?;
        let streaming_mib = if cfg!(feature = "full-world") {
            option_env!("SPHERE_WORLD_STREAM_MIB").unwrap_or("640").parse::<u32>()
                .map_err(|e| format!("invalid world streaming budget: {e}"))?
        } else { 256 };
        set_limit(GameLimit::StreamingMemory, streaming_mib * 1024 * 1024)
            .map_err(|e| format!("streaming budget: {e:?}"))?;
        events::subscribe(&[event_kind::FRAME_BEGIN]);
        sa_mod::info(&format!("br-game-profile: streaming memory {streaming_mib} MiB"));
        Ok(())
    }
    fn settings(&mut self) {
        if let Err(e) = sa_mod::display::request_video_mode(1920, 1080, false) {
            sa_mod::info(&format!("1080p request failed: {e:?}"));
        }
    }
    fn event(&mut self, event: Event) {
        if !matches!(event, Event::FrameBegin(_)) {
            return;
        }
        let Some(world) = state::world() else { return };
        if world.time_ms.wrapping_sub(self.last_sample) < 250 {
            return;
        }
        self.last_sample = world.time_ms;
        let Some(player) = state::player() else {
            return;
        };
        if player.ped.in_world {
            let _ = set_hud_visible(false);
        }
        if let Some(cam) = state::camera() {
            sa_mod::info(&format!(
                "br_camera t={} xyz={:.3},{:.3},{:.3} forward={:.4},{:.4},{:.4} mode={} fov={:.1}",
                world.time_ms,
                cam.pos.x,
                cam.pos.y,
                cam.pos.z,
                cam.front.x,
                cam.front.y,
                cam.front.z,
                cam.mode,
                cam.fov,
            ));
        }
        let pos = player.ped.pos;
        let ridden = player.ped.vehicle.and_then(state::vehicle);
        sa_mod::info(&format!(
            "br_observe t={} xyz={:.3},{:.3},{:.3} in_world={} hp={:.1} driver={} model={:?}",
            world.time_ms,
            pos.x,
            pos.y,
            pos.z,
            player.ped.in_world,
            player.ped.health,
            ridden
                .as_ref()
                .is_some_and(|v| player.handle.is_some() && v.driver == player.handle),
            ridden.map(|v| v.model),
        ));
    }
}

sa_mod::entry!(RouteStart);
