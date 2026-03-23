from .utils import clamp

class PID:
    def __init__(self, kp, ki, kd, out_min, out_max):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_min, self.out_max = out_min, out_max
        self.i = 0.0
        self.prev_err = None

    def reset(self):
        self.i = 0.0
        self.prev_err = None

    def update(self, pv, sp, dt):
        err = pv - sp
        d = 0.0
        if self.prev_err is not None and dt > 0:
            d = (err - self.prev_err) / dt
        self.prev_err = err
        self.i += err * dt
        self.i = clamp(self.i, -1000.0, 1000.0)
        u = self.kp * err + self.ki * self.i + self.kd * d
        return clamp(u, self.out_min, self.out_max)
