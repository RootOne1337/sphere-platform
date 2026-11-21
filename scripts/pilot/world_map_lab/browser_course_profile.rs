use sa_mod::game::{
    GameLimit, GameOption, set_frame_limit, set_hud_visible, set_limit, set_option,
};
use sa_mod::{Event, Mod, event_kind, events, state};

#[derive(Default)]
struct RouteStart {
    last_sample: u32,
    hud_hidden: bool,
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
        set_frame_limit(30).map_err(|e| format!("frame limit: {e:?}"))?;
        set_limit(GameLimit::StreamingMemory, 256 * 1024 * 1024)
            .map_err(|e| format!("streaming budget: {e:?}"))?;
        events::subscribe(&[event_kind::FRAME_BEGIN]);
        sa_mod::info("br-game-profile: start staged mission with 256 MiB streaming memory");
        Ok(())
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
        if player.ped.in_world && !self.hud_hidden {
            self.hud_hidden = set_hud_visible(false).is_ok();
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
