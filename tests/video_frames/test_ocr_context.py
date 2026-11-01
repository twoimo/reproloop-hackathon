from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import tempfile
import unittest
from reproloop.video_frames import FrameObservation,with_ocr_context

MEDIA='a'*64


def frame(i,point=None):
    digest=sha256(str(i).encode()).hexdigest()
    candidate=None if point is None else {'red_marker_candidate':dict(center=list(point),bounds=[*point,*point],source_png_sha256=digest)}
    return FrameObservation(i*1000,digest,720,1280,MEDIA,'data:image/png;base64,PRIVATE',candidate,'ABSENT' if point is None else 'CANDIDATE')


def region(text='visible words',bounds=None,confidence=0.9):
    return dict(text=text,bounds=bounds or [0,0,20,20],confidence=confidence)


class OCRTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'OCR.json'
        self.frames=(frame(0),frame(1,(10,10)))
        self.value=dict(schema_version=1,decoder='macOS Vision',media_sha256=MEDIA,tool_source_sha256='b'*64,attestation=False,
                        frames=[dict(timestamp_ms=f.timestamp_ms,png_sha256=f.png_sha256,regions=[region()]) for f in self.frames])
    def tearDown(self):self.tmp.cleanup()
    def build(self):
        self.path.write_text(json.dumps(self.value));return with_ocr_context(self.frames,self.path,MEDIA)
    def test_default_summary_byte_compatibility(self):
        f=self.frames[0]
        old=json.dumps(dict(decoded_timestamp_ms=f.timestamp_ms,pointer_status=f.pointer_status,pointer_candidate=f.pointer_candidate,
            notice='UNTRUSTED SAME-VIDEO PIXEL OBSERVATION. NotAuthorization; not touch attestation or action authority.'),separators=(',',':'),ensure_ascii=True)
        self.assertEqual(f.observer_summary(),old)
        self.assertNotIn('ocr_',f.response_items()[0]['text'])
        self.assertNotIn('PRIVATE',repr(f))
    def test_all_text_retained_and_plural_overlap(self):
        self.value['frames'][0]['regions']=[region('first'),region('second'),region('elsewhere',[100,100,120,120]),region('low',[0,0,20,20],0.6)]
        result=self.build()
        self.assertEqual(len(result[0].ocr_regions),4)
        self.assertEqual([r['text'] for r in result[1].prior_pointer_text_candidates],['first','second'])
        self.assertTrue(result[1].pointer_location_changed)
        summary=json.loads(result[1].observer_summary())
        self.assertEqual(summary['ocr_observer'],'macOS Vision')
        self.assertEqual(len(summary['previous_visible_text_candidates']),2)
        self.assertEqual(result[1].data_url,self.frames[1].data_url)
    def test_exact_exclusive_edges_and_no_nearest(self):
        for point,matches in (((0,0),1),((19,19),1),((20,19),0),((19,20),0),((21,21),0)):
            self.frames=(frame(0),frame(1,point))
            self.assertEqual(len(self.build()[1].prior_pointer_text_candidates),matches)
    def test_jitter_absent_keeps_point_and_no_duplicate_events(self):
        self.frames=(frame(0,(10,10)),frame(1,(13,13)),frame(2),frame(3,(13,13)),frame(4,(17,13)))
        self.value['frames']=[dict(timestamp_ms=f.timestamp_ms,png_sha256=f.png_sha256,regions=[region()]) for f in self.frames]
        result=self.build()
        self.assertEqual([r.pointer_location_changed for r in result],[True,False,None,False,True])
        self.assertEqual(result[0].prior_pointer_text_candidates,())
        self.assertEqual(result[3].prior_pointer_text_candidates,())
        self.assertEqual(result[4].prior_pointer_text_candidates[0]['timestamp_ms'],3000)
    def test_immediately_previous_frame_not_last_point_frame(self):
        self.frames=(frame(0,(50,50)),frame(1),frame(2,(10,10)))
        self.value['frames']=[dict(timestamp_ms=f.timestamp_ms,png_sha256=f.png_sha256,regions=[region('row'+str(i))]) for i,f in enumerate(self.frames)]
        result=self.build()
        self.assertEqual(result[2].prior_pointer_text_candidates[0]['text'],'row1')
    def test_bad_bounds_type_bool_float_and_range(self):
        for bounds in ([0,0,20.0,20],[False,0,20,20],[0,0,721,20],[0,0,20,1281],[20,0,0,20],[0,0,0,20]):
            self.value['frames'][0]['regions']=[region(bounds=bounds)]
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):self.build()
    def test_bad_strings_confidence_and_limits(self):
        for bad in (region(text='x'*257),region(text=''),region(text='line\ncontrol'),region(confidence=True),region(confidence=1.1),region(confidence=float('nan'))):
            self.value['frames'][0]['regions']=[bad]
            with self.assertRaises(ValueError):self.build()
        self.value['frames'][0]['regions']=[region()]*65
        with self.assertRaises(ValueError):self.build()
    def test_source_binding_and_timestamp_mismatches(self):
        for key,bad in (('png_sha256','c'*64),('timestamp_ms',1),('timestamp_ms',False)):
            old=self.value['frames'][0][key];self.value['frames'][0][key]=bad
            with self.assertRaises(ValueError):self.build()
            self.value['frames'][0][key]=old
        self.value['media_sha256']='c'*64
        with self.assertRaises(ValueError):self.build()
    def test_count_extra_fields_source_paths_and_symlink(self):
        row=self.value['frames'].pop()
        with self.assertRaises(ValueError):self.build()
        self.value['frames'].append(row);self.value['extra_path']='/private/notread'
        with self.assertRaises(ValueError):self.build()
        del self.value['extra_path'];self.build()
        link=self.root/'link.json';link.symlink_to(self.path)
        with self.assertRaises(OSError):with_ocr_context(self.frames,link,MEDIA)
        with self.assertRaises(ValueError):with_ocr_context(self.frames,str(self.root/'../OCR.json'),MEDIA)
    def test_observation_pointer_validation(self):
        self.frames=(self.frames[0],replace(self.frames[1],source_media_sha256='d'*64))
        with self.assertRaises(ValueError):self.build()
        self.frames=(frame(0),frame(1,(True,10)))
        with self.assertRaises(ValueError):self.build()

if __name__=='__main__':unittest.main()
