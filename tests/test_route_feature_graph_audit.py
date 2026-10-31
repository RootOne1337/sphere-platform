import hashlib
import json
import sqlite3

import numpy as np

from scripts.pilot.audit_route_feature_graph import audit


def test_empty_native_match_rows_and_watermark_diagnostics_are_read_only(tmp_path):
    database=tmp_path/'database.db'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE images(image_id INTEGER,name TEXT)')
        db.executemany('INSERT INTO images VALUES(?,?)',[(1,'00000000.png'),(2,'00000001.png'),(3,'00000002.png')])
        db.execute('CREATE TABLE keypoints(image_id INTEGER,rows INTEGER,cols INTEGER,data BLOB)')
        points=np.array([[800,400],[400,200]],dtype='<f4')
        db.executemany('INSERT INTO keypoints VALUES(?,?,?,?)',[(i,2,2,points.tobytes()) for i in (1,2,3)])
        db.execute('CREATE TABLE matches(pair_id INTEGER,rows INTEGER,cols INTEGER,data BLOB)')
        db.execute('INSERT INTO matches VALUES(?,?,?,?)',(2147483647+2,0,2,None))
        matches=np.array([[0,0],[1,1]],dtype='<u4')
        db.execute('INSERT INTO matches VALUES(?,?,?,?)',(2*2147483647+3,2,2,matches.tobytes()))
        db.execute('CREATE TABLE two_view_geometries(config INTEGER)')
        db.execute('INSERT INTO two_view_geometries VALUES(7)')
    index=tmp_path/'reconstruction-input.json'
    index.write_text(json.dumps(dict(source_manifest_sha256='a'*64,geometry=[1000,600],images=[
        dict(image=f'images/{i:08}.png',relative_ticks_90k=i*45000) for i in range(3)])))
    before=hashlib.sha256(database.read_bytes()).hexdigest()
    report=audit(tmp_path)
    assert report['verified_configurations']=={'WATERMARK':1}
    assert report['adjacent_matches']['observations']==2
    assert report['right_overlay_region']['fraction_below_1_5px']==1.
    assert report['adjacent_pairs'][0]['raw_matches']==0
    assert not report['source_modified'] and report['physical_actions']==0
    assert hashlib.sha256(database.read_bytes()).hexdigest()==before
