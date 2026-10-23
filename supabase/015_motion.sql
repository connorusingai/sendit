-- Stomped database, version 15: let the app save a motion log next to each video.
--   While you record, the app logs the phone's gyroscope (spin rate) and accelerometer. It's saved as
--   <your id>/<video name>.motion.json in the same storage folder as the video, for the trick AI.
--   The storage bucket only accepted videos, so this adds JSON. Same rules as videos: you can only
--   upload into your own folder, and deleting a clip or your account deletes its motion file too.
-- Paste into Supabase > SQL Editor and click Run. No existing data is changed.

update storage.buckets
set allowed_mime_types = array['video/mp4','video/quicktime','video/webm','application/json']
where id = 'clips';

-- Check: should list 4 types, ending in application/json
select allowed_mime_types from storage.buckets where id = 'clips';
