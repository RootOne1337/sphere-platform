//! Independent course observer for the game fixture. Never feeds the controller.
type Point = [f32; 3];

#[derive(Default)]
pub struct Course {
    next: usize,
    last: Option<(u32, Point)>,
}

fn distance(a: Point, b: Point) -> f32 {
    (a[0] - b[0]).hypot(a[1] - b[1]).hypot(a[2] - b[2])
}

impl Course {
    pub fn sample(&mut self, gates: &[Point], now: u32, pos: Point) -> bool {
        let previous = self.last.replace((now, pos));
        let from = previous
            .filter(|(stamp, prev)| {
                let dt = now.wrapping_sub(*stamp);
                dt > 0 && dt <= 1000 && distance(*prev, pos) <= 1.0 + 0.060 * dt as f32
            })
            .map_or(pos, |(_, p)| p);
        let dx = pos[0] - from[0];
        let dy = pos[1] - from[1];
        let len2 = dx * dx + dy * dy;
        let mut last_t = 0.0;
        while let Some(gate) = gates.get(self.next) {
            let t = if len2 < 1e-6 {
                0.0
            } else {
                (((gate[0] - from[0]) * dx + (gate[1] - from[1]) * dy) / len2).clamp(0., 1.)
            };
            let horizontal = (gate[0] - from[0] - t * dx).hypot(gate[1] - from[1] - t * dy);
            let height = from[2] + t * (pos[2] - from[2]);
            if t < last_t || horizontal > 2.75 || (gate[2] - height).abs() > 1.75 {
                break;
            }
            self.next += 1;
            last_t = t;
        }
        !gates.is_empty() && self.next == gates.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn full_circuit_requires_far_side_before_return() {
        let gates = [
            [0., 0., 0.],
            [8., 0., 0.],
            [8., 8., 0.],
            [0., 8., 0.],
            [0., 0., 0.],
        ];
        let mut course = Course::default();
        assert!(!course.sample(&gates, 100, gates[0]));
        assert!(!course.sample(&gates, 300, gates[4]));
        for (i, p) in gates[1..].iter().enumerate() {
            assert_eq!(course.sample(&gates, 500 + 200 * i as u32, *p), i == 3);
        }
    }

    #[test]
    fn fast_crossings_are_seen_and_other_floors_are_excluded() {
        let gates = [[0., 0., 0.], [6., 0., 0.], [12., 0., 0.]];
        let mut course = Course::default();
        assert!(!course.sample(&gates, 200, [0., 0., 5.]));
        assert!(!course.sample(&gates, 400, [12., 0., 5.]));
        assert!(!course.sample(&gates, 600, [0., 0., 1.]));
        assert!(course.sample(&gates, 800, [12., 0., 1.]));
    }

    #[test]
    fn disconnected_samples_cannot_cover_unobserved_gates() {
        for later in [250, 2200] {
            let mut course = Course::default();
            let gates = [[0., 0., 0.], [6., 0., 0.], [12., 0., 0.]];
            assert!(!course.sample(&gates, 200, gates[0]));
            assert!(!course.sample(&gates, later, gates[2]));
        }
    }
}
