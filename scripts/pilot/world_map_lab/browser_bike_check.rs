//! Browser-only component check using the same CBike and CPhysical code as sa-game.
use sa_core::mem::{GPtr, GameData};
use sa_input::pad;
use wasm_bindgen::prelude::*;

fn write<T: GameData>(base: GPtr<u8>, offset: isize, value: T) {
    base.byte_add(offset).cast::<T>().write(value);
}

fn read_float(base: GPtr<u8>, offset: isize) -> f32 {
    base.byte_add(offset).cast::<f32>().read()
}

// Run in a fresh module instance, independently from gameplay and its player.
#[wasm_bindgen]
pub fn check_bike_response() -> Result<Vec<f32>, JsValue> {
    crate::arena::map_image(crate::arena::Image::Builtin, "bike component check")
        .map_err(|e| JsValue::from_str(&e))?;
    crate::native::install();
    sa_core::timer::TIME_STEP.set(1.0);
    let mut bike_storage = Box::new([0_u32; 0x900 / 4]);
    let mut matrix_storage = [0_f32; 16];
    let mut handling_storage = [0_f32; 64];
    let bike = GPtr::<u8>::from_addr(bike_storage.as_mut_ptr() as usize);
    let matrix = GPtr::<u8>::from_addr(matrix_storage.as_mut_ptr() as usize);
    let handling = GPtr::<u8>::from_addr(handling_storage.as_mut_ptr() as usize);
    write(bike, 0x14, matrix);
    write(bike, 0x384, handling);
    // Controlled test inputs. The game supplies these fields from the model at runtime.
    write(bike, 0x424, -1_i8);
    write(handling, 0xA0, 30_f32);
    for offset in [0, 0x14, 0x28] {
        write(matrix, offset, 1_f32);
    }
    write(bike, 0x48, 0.15_f32);
    write(bike, 0x8C, 200_f32);
    write(bike, 0x90, 100_f32);
    let pad = pad::get_pad(0);
    let mut results = Vec::new();
    for (gas, brake, steer) in [
        (0, 0, 0),
        (255, 0, 0),
        (255, 0, -128),
        (255, 0, -128),
        (255, 0, -128),
        (0, 0, 0),
        (0, 255, 0),
        (0, 0, 0),
    ] {
        write(pad, pad::BUTTON_CROSS, gas as i16);
        write(pad, pad::BUTTON_SQUARE, brake as i16);
        write(pad, pad::LEFT_STICK_X, steer as i16);
        sa_veh::bike_controls::bike_process_control_inputs(bike, 0);
        results.extend([
            read_float(bike, 0x49C),
            read_float(bike, 0x4A0),
            read_float(bike, 0x494),
        ]);
    }
    let mut down = [0_f32, 0.0, -1.0];
    let mut contact = [0_f32; 3];
    for length in [1.0, 0.75, 0.5] {
        let mut force = 0_f32;
        write(bike, 0x4C, 0_f32);
        sa_world::physical::spring::apply_spring_collision(
            bike,
            1.0,
            GPtr::from_addr(down.as_mut_ptr() as usize),
            GPtr::from_addr(contact.as_mut_ptr() as usize),
            length,
            1.0,
            GPtr::from_addr(&mut force as *mut f32 as usize),
        );
        results.extend([force, read_float(bike, 0x4C)]);
    }
    Ok(results)
}
#[wasm_bindgen]
pub fn check_image_slots(paths: Vec<String>, last_sectors: Vec<u32>) -> Result<Vec<u32>, JsValue> {
    use crate::bind;
    use crate::platform::webfs::WebFs;
    use sa_platform::fs::MemFs;
    use sa_platform::input::InputState;
    use sa_platform::vfs::{FileTable, Vfs};
    use sa_platform::win32::{MessageQueue, Win32Time};
    use sa_stream::{cdstream, streaming};

    if paths.is_empty() || paths.len() > 24 || paths.len() != last_sectors.len() {
        return Err(JsValue::from_str("invalid set of test archives"));
    }
    crate::arena::map_image(crate::arena::Image::Builtin, "archive readback")
        .map_err(|e| JsValue::from_str(&e))?;
    crate::native::install();
    bind::install(bind::Platform {
        vfs: Vfs::new(Box::new(WebFs), Box::new(MemFs::default())),
        files: FileTable::default(),
        time: Win32Time::new(crate::det::GameClock::default()),
        queue: MessageQueue::new(bind::HWND),
        input: InputState::default(),
        last_error: 0,
        undelivered: Default::default(),
        calls: Default::default(),
    });
    // Use the engine's synchronous sector reader in this dedicated test worker.
    let mut channel = [0u32; 64];
    let previous = cdstream::CD_STREAMS.get();
    cdstream::CD_STREAMS.set(GPtr::from_raw(channel.as_mut_ptr()).cast());
    let readback = (|| {
        let mut result = Vec::new();
        let mut buf = [0u8; 2048];
        for (i, (name, last)) in paths.iter().zip(&last_sectors).enumerate() {
            if !name.is_ascii() || name.len() >= 40 || name.contains('\0') || *last >= (1 << 20) {
                return Err(JsValue::from_str("invalid game archive path or size"));
            }
            let path = std::ffi::CString::new(name.as_str()).unwrap();
            let id = streaming::add_image_to_list(GPtr::from_addr(path.as_ptr() as usize), 1);
            if id != i as i32 {
                return Err(JsValue::from_str("engine rejected an image slot"));
            }
        }
        // Read after registering all images to catch overwritten descriptors and aliasing.
        for (i, &last) in last_sectors.iter().enumerate() {
            let handle = streaming::file_handle(i as i32);
            result.push(handle >> 24);
            for sector in [0, last] {
                buf.fill(0);
                let ok = cdstream::cd_stream_read(
                    0,
                    GPtr::from_raw(buf.as_mut_ptr()),
                    handle | sector,
                    1,
                );
                if ok == 0 {
                    return Err(JsValue::from_str("CdStreamRead failed"));
                }
                result.push(buf.iter().fold(2166136261u32, |h, &b| {
                    (h ^ u32::from(b)).wrapping_mul(16777619)
                }));
            }
        }
        Ok(result)
    })();
    cdstream::CD_STREAMS.set(previous);
    readback
}
