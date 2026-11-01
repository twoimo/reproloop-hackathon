import io
import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from reproloop.video_frames import build_frame_observations, _red_candidate

MEDIA = 'a'*64


def image(points=(),color=(255,0,0)):
    im=Image.new('RGB',(720,1280),'white')
    for x,y in points:im.putpixel((x,y),color)
    stream=io.BytesIO();im.save(stream,format='PNG');return stream.getvalue()


class FrameTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'decode.json';self.raw=image()
        self.value=dict(schema_version=1,decoder='macOS AVFoundation',media_sha256=MEDIA,
            video_tracks=1,audio_tracks=0,duration_seconds=4,attestation=False,
            coverage_judgment='REQUIRES_HUMAN_INSPECTION',frames=[])
        self.add(self.raw,0,0.25)
    def tearDown(self):self.tmp.cleanup()
    def add(self,raw,actual,requested):
        filename=f'frame-{len(self.value["frames"]):02d}.png'
        (self.root/filename).write_bytes(raw)
        self.value['frames'].append(dict(file=filename,sha256=sha256(raw).hexdigest(),width=720,height=1280,
                                        decoded_seconds=actual,requested_seconds=requested))
    def build(self,markers=False):
        self.path.write_text(json.dumps(self.value))
        return build_frame_observations(self.path,MEDIA,native_marker_candidates=markers)
    def test_normal_and_response_shape(self):
        self.add(self.raw,3.1239,3.25)
        frames=self.build();self.assertEqual([f.timestamp_ms for f in frames],[0,3123])
        self.assertEqual(frames[0].pointer_status,'NOT_REQUESTED')
        self.assertNotIn('base64',repr(frames[0]))
        parts=frames[0].response_items()
        self.assertEqual([p['type'] for p in parts],['input_text','input_image'])
        self.assertEqual(parts[1]['detail'],'high');self.assertIn('NotAuthorization',parts[0]['text'])
        self.assertEqual(json.loads(parts[0]['text'])['decoded_timestamp_ms'],0)
    def test_none_and_header_only(self):
        for raw in (self.raw,image([(30,2),(31,31)])):
            candidate,status=_red_candidate(raw,sha256(raw).hexdigest())
            self.assertIsNone(candidate);self.assertEqual(status,'ABSENT')
    def test_isolated_compact_integer_candidate(self):
        raw=image([(100,100),(101,100),(101,101)])
        candidate,status=_red_candidate(raw,sha256(raw).hexdigest())
        self.assertEqual(status,'CANDIDATE')
        self.assertEqual(candidate,{'red_marker_candidate':dict(bounds=[100,100,101,101],center=[100,100],source_png_sha256=sha256(raw).hexdigest())})
    def test_multiple_diffuse_and_pixel_caps(self):
        for points in ([(100,100),(110,110)],[(x,100) for x in range(10)],
                       [(x,y+100) for x in range(5) for y in range(5)],[(x,100) for x in range(65)]):
            candidate,status=_red_candidate(image(points),'a'*64)
            self.assertIsNone(candidate);self.assertEqual(status,'AMBIGUOUS')
    def test_threshold_boundaries(self):
        for color,status in (((100,30,30),'CANDIDATE'),((99,0,0),'ABSENT'),
                             ((100,31,0),'ABSENT'),((100,0,31),'ABSENT'),((100,30,31),'ABSENT')):
            with self.subTest(color=color):self.assertEqual(_red_candidate(image([(50,32)],color),'a'*64)[1],status)
    def test_optin_candidate_in_observation(self):
        raw=image([(20,50)]);(self.root/'frame-00.png').write_bytes(raw)
        self.value['frames'][0]['sha256']=sha256(raw).hexdigest()
        self.assertEqual(self.build(True)[0].pointer_status,'CANDIDATE')
    def test_wrong_png_hash(self):
        self.value['frames'][0]['sha256']='b'*64
        with self.assertRaises(ValueError):self.build()
    def test_mismatched_media(self):
        self.value['media_sha256']='b'*64
        with self.assertRaises(ValueError):self.build()
    def test_traversal_absolute_and_extra_paths(self):
        for name in ('../frame-00.png','/frame-00.png','sub/frame-00.png','frame-0.png'):
            self.value['frames'][0]['file']=name
            with self.assertRaises(ValueError):self.build()
        self.value['frames'][0]['file']='frame-00.png';self.value['source_path']='/unrelated/private'
        with self.assertRaises(ValueError):self.build()
    def test_leaf_and_parent_symlinks(self):
        source=self.root/'frame-00.png';source.unlink();source.symlink_to(self.root/'else.png')
        with self.assertRaises(OSError):self.build()
        source.unlink();source.write_bytes(self.raw);self.build()
        alias=self.root/'alias';alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(OSError):build_frame_observations(alias/'decode.json',MEDIA)
        link=self.root/'linked.json';link.symlink_to(self.path)
        with self.assertRaises(OSError):build_frame_observations(link,MEDIA)
    def test_duplicate_actual_timestamp_deduplicates_same_hash_only(self):
        self.add(self.raw,0,3.25);self.assertEqual(len(self.build()),1)
        different=image([(80,80)]);(self.root/'frame-01.png').write_bytes(different)
        self.value['frames'][1]['sha256']=sha256(different).hexdigest()
        with self.assertRaises(ValueError):self.build()
    def test_nondecreasing_actual_but_same_millisecond_rejected(self):
        self.add(self.raw,0.0001,3.25)
        with self.assertRaises(ValueError):self.build()
    def test_boolean_nonfinite_and_reverse_times(self):
        for bad in (True,float('inf'),float('nan'),-1,5):
            self.value['frames'][0]['decoded_seconds']=bad
            with self.assertRaises(ValueError):self.build()
        self.value['frames'][0]['decoded_seconds']=2;self.add(self.raw,1,3.25)
        with self.assertRaises(ValueError):self.build()
    def test_duration_and_track_contract(self):
        for key,bad in (('duration_seconds',True),('duration_seconds',46),('duration_seconds',0),
                        ('audio_tracks',1),('video_tracks',True),('decoder','other')):
            original=self.value[key];self.value[key]=bad
            with self.assertRaises(ValueError):self.build()
            self.value[key]=original
    def test_large_wrong_dimensions_and_header_only_png(self):
        for raw in (b'x'*(8*1024*1024+1),self.raw[:33]):
            (self.root/'frame-00.png').write_bytes(raw);self.value['frames'][0]['sha256']=sha256(raw).hexdigest()
            with self.assertRaises((ValueError,RuntimeError)):self.build()
        small=io.BytesIO();Image.new('RGB',(10,10),'white').save(small,format='PNG')
        raw=small.getvalue();(self.root/'frame-00.png').write_bytes(raw)
        self.value['frames'][0]['sha256']=sha256(raw).hexdigest()
        with self.assertRaises(ValueError):self.build()
        self.value['frames'][0]['width']=True
        with self.assertRaises(ValueError):self.build()
    def test_missing_optional_dependency_clear_error(self):
        with patch.dict('sys.modules',{'PIL':None}):
            with self.assertRaisesRegex(ImportError,'Pillow==13.0.0'):_red_candidate(self.raw,'a'*64)
    def test_frame_count_bound(self):
        self.value['frames']=[]
        with self.assertRaises(ValueError):self.build()
        self.value['frames']=[{}]*17
        with self.assertRaises(ValueError):self.build()

if __name__=='__main__':unittest.main()
