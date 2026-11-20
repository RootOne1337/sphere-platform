//! Local sa-engine test fixture. Engine state drives the camera and the observer only.
use sa_mod::script::Arg::{Float, Int};
use sa_mod::{
    Event, Mod, Vec3, VehicleRef, entities, event_kind, models, objects, script, state, world,
};
mod native_progress;
include!("points.rs");

#[derive(Default)]
struct Journey {
    bike: Option<VehicleRef>,
    first_person: bool,
    boarded: bool,
    exited: bool,
    displaced: bool,
    away: bool,
    recovery_frames: u8,
    recovered: bool,
    was_mounted: bool,
    pending: bool,
    wait_frames: u16,
    finished: bool,
    course: native_progress::Course,
    rode_course: bool,
    last_sample: u32,
}

impl Journey {
    fn prepare(&mut self) -> Result<(), String> {
        if self.bike.is_some() || self.pending {
            return Err("scenario already active".into());
        }
        for p in [START, PARK] {
            script::run(0x04e4, &[Float(p[0]), Float(p[1])]).map_err(|e| format!("{e:?}"))?;
        }
        models::request(462, false).map_err(|e| format!("{e:?}"))?;
        self.pending = true;
        self.wait_frames = 0;
        Ok(())
    }

    fn supported(p: [f32; 3]) -> bool {
        let result = script::run(
            0x02ce,
            &[
                Float(p[0]),
                Float(p[1]),
                Float(p[2] + 2.0),
                script::Arg::Out,
            ],
        );
        result
            .ok()
            .and_then(|r| r.outputs.first().copied())
            .is_some_and(|bits| (f32::from_bits(bits) - p[2]).abs() < 0.85)
    }

    fn start(&mut self) -> Result<(), String> {
        if self.bike.is_some() {
            return Err("scenario already started".into());
        }
        let player = state::player().ok_or("player unavailable")?;
        let ped = player.handle.ok_or("no player body")?;
        if !player.ped.in_world || player.ped.vehicle.is_some() {
            return Err("start on foot in the loaded scene".into());
        }
        let bike = entities::create_vehicle(
            462,
            Vec3::new(PARK[0], PARK[1], PARK[2] + 0.45),
            PARK_HEADING,
        )
        .map_err(|e| format!("{e:?}"))?;
        if let Err(err) =
            world::set_ped_position(ped, Vec3::new(START[0], START[1], START[2] + 1.0))
        {
            let _ = entities::destroy_vehicle(bike);
            return Err(format!("{err:?}"));
        }
        world::set_ped_heading(ped, START_HEADING).map_err(|e| {
            let _ = entities::destroy_vehicle(bike);
            format!("{e:?}")
        })?;
        self.bike = Some(bike);
        self.first_person = true;
        sa_mod::info(&format!(
            "sphere_scenario event=start route={ROUTE_SHA256} gates={}",
            GATES.len()
        ));
        Ok(())
    }

    fn impact(&mut self) -> Result<(), String> {
        let bike = self.bike.ok_or("no scenario")?;
        let v = state::vehicle(bike).ok_or("vehicle unavailable")?;
        let player = state::player().ok_or("player unavailable")?;
        if self.displaced || player.ped.vehicle != Some(bike) || v.driver != player.handle {
            return Err("lateral disturbance requires the player driving the test scooter".into());
        }
        let motion = state::vehicle_motion(bike).ok_or("motion unavailable")?;
        let speed = v.move_speed;
        // Engine velocity uses units per 1/50 s. Add a perpendicular 8 units/s once.
        world::set_vehicle_speed(
            bike,
            Vec3::new(
                speed.x + 0.16 * v.forward.y,
                speed.y - 0.16 * v.forward.x,
                speed.z,
            ),
            motion.turn_speed,
        )
        .map_err(|e| format!("{e:?}"))?;
        self.displaced = true;
        sa_mod::info("sphere_scenario event=lateral_velocity_step units_per_sec=8");
        Ok(())
    }

    fn tick(&mut self) {
        if self.pending {
            self.wait_frames += 1;
            if self.wait_frames % 10 == 0
                && Self::supported(START)
                && Self::supported(PARK)
                && models::info(462).is_some_and(|(_, loaded)| loaded)
            {
                self.pending = false;
                let result = self.start();
                let _ = models::release(462);
                if let Err(err) = result {
                    sa_mod::info(&format!("sphere_scenario start_failed={err}"));
                }
            } else if self.wait_frames > 600 {
                self.pending = false;
                let _ = models::release(462);
                sa_mod::info("sphere_scenario event=ground_or_vehicle_not_loaded");
            }
        }
        let Some(bike) = self.bike else { return };
        let Some(player) = state::player() else {
            return;
        };
        let Some(ped) = player.handle else { return };
        let mut camera_on_head = false;
        if self.first_person {
            if let (Some(head), Some(body)) =
                (objects::ped_bone_matrix(ped, 5), state::ped_matrix(ped))
            {
                let forward = body.forward;
                let eye = Vec3::new(
                    head.pos.x + forward.x * 0.16,
                    head.pos.y + forward.y * 0.16,
                    head.pos.z + 0.055,
                );
                let a = script::run(
                    0x015f,
                    &[
                        Float(eye.x),
                        Float(eye.y),
                        Float(eye.z),
                        Float(0.),
                        Float(0.),
                        Float(0.),
                    ],
                );
                let b = script::run(
                    0x0160,
                    &[
                        Float(eye.x + forward.x * 6.),
                        Float(eye.y + forward.y * 6.),
                        Float(eye.z + forward.z * 6.),
                        Int(2),
                    ],
                );
                if a.is_err() || b.is_err() {
                    self.first_person = false;
                    let _ = script::run(0x02eb, &[]);
                    sa_mod::info("sphere_scenario event=camera_command_failed");
                } else {
                    camera_on_head = true;
                }
            }
        }
        let Some(w) = state::world() else { return };
        if w.time_ms.wrapping_sub(self.last_sample) < 200 {
            return;
        }
        self.last_sample = w.time_ms;
        let mounted = player.ped.vehicle == Some(bike)
            && state::vehicle(bike).is_some_and(|v| v.driver == Some(ped));
        if mounted {
            self.exited = false;
        }
        if mounted && !self.boarded {
            self.boarded = true;
            sa_mod::info("sphere_scenario event=boarded");
        }
        let p = player.ped.pos;
        if mounted && !self.rode_course && self.course.sample(GATES, w.time_ms, [p.x, p.y, p.z]) {
            self.rode_course = true;
            sa_mod::info("sphere_scenario event=drive_route_complete");
        }
        if mounted && self.displaced && !self.recovered {
            let distance = ROAD
                .windows(2)
                .map(|ab| {
                    let (a, b) = (ab[0], ab[1]);
                    let (x, y) = (b[0] - a[0], b[1] - a[1]);
                    let t = (((p.x - a[0]) * x + (p.y - a[1]) * y) / (x * x + y * y).max(1e-6))
                        .clamp(0., 1.);
                    ((p.x - a[0] - t * x).powi(2)
                        + (p.y - a[1] - t * y).powi(2)
                        + (p.z - a[2] - t * (b[2] - a[2])).powi(2))
                    .sqrt()
                })
                .fold(f32::INFINITY, f32::min);
            if distance > 6.0 && !self.away {
                self.away = true;
                sa_mod::info("sphere_scenario event=displacement_verified");
            }
            let speed = state::vehicle(bike)
                .map(|v| v.move_speed.x.hypot(v.move_speed.y))
                .unwrap_or(0.);
            self.recovery_frames = if self.away && distance < 2.0 && speed > 0.025 {
                self.recovery_frames + 1
            } else {
                0
            };
            if self.recovery_frames >= 5 {
                self.recovered = true;
                sa_mod::info("sphere_scenario event=returned_to_route");
            }
        }
        if !mounted && self.was_mounted {
            let q = ROAD.last().unwrap();
            let parked = self.rode_course
                && state::vehicle(bike).is_some_and(|v| {
                    (v.pos.x - q[0]).hypot(v.pos.y - q[1]) < 3.0
                        && (v.pos.z - q[2]).abs() < 1.5
                        && v.move_speed.x.hypot(v.move_speed.y) < 0.025
                });
            self.exited = parked;
            sa_mod::info(if parked {
                "sphere_scenario event=parked_and_exited"
            } else {
                "sphere_scenario event=unplanned_dismount"
            });
        }
        self.was_mounted = mounted;
        let error = ((p.x - GOAL[0]).powi(2) + (p.y - GOAL[1]).powi(2)).sqrt();
        if self.exited
            && player.ped.vehicle.is_none()
            && player.ped.in_world
            && (!self.displaced || self.recovered)
            && !self.finished
            && error < 1.0
            && (p.z - GOAL[2]).abs() < 1.6
            && player.ped.health > 0.0
        {
            self.finished = true;
            sa_mod::info("sphere_scenario event=goal_on_foot");
        }
        sa_mod::info(&format!(
            "sphere_truth t={} pos={:.3},{:.3},{:.3} mounted={} health={:.1} head={}",
            w.time_ms, p.x, p.y, p.z, mounted, player.ped.health, camera_on_head
        ));
    }
}

impl Mod for Journey {
    fn init(&mut self) -> Result<(), String> {
        sa_mod::events::subscribe(&[event_kind::FRAME_BEGIN, event_kind::KEY_DOWN]);
        Ok(())
    }
    fn event(&mut self, event: Event) {
        let result = match event {
            Event::FrameBegin(_) => {
                self.tick();
                return;
            }
            Event::KeyDown(0x75) => self.prepare(),
            Event::KeyDown(0x76) => self.impact(),
            _ => return,
        };
        if let Err(e) = result {
            sa_mod::info(&format!("sphere_scenario error={e}"))
        }
    }
}
sa_mod::entry!(Journey);
