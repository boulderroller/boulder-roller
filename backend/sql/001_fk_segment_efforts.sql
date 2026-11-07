-- Foreign keys for segment_efforts
ALTER TABLE public.segment_efforts
  ADD CONSTRAINT fk_segment_efforts_ride
    FOREIGN KEY (ride_id) REFERENCES public.rides(id) ON UPDATE NO ACTION ON DELETE NO ACTION;

ALTER TABLE public.segment_efforts
  ADD CONSTRAINT fk_segment_efforts_segment
    FOREIGN KEY (segment_id) REFERENCES public.segments(id) ON UPDATE NO ACTION ON DELETE NO ACTION;

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_segment_efforts_ride_id ON public.segment_efforts(ride_id);
CREATE INDEX IF NOT EXISTS idx_segment_efforts_segment_id ON public.segment_efforts(segment_id);
