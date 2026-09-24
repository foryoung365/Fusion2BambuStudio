"""Local-only visual interaction harness. Never controls Fusion or exports/prints."""
import json
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from BambuPlateStudio.core.model import Body,Session,PrintUnit,Plate,Placement,new_id
from BambuPlateStudio.core.auto_orient import suggest,suggest_many,apply_rotation
from BambuPlateStudio.core.auto_place import suggest as suggest_positions,apply_positions
from BambuPlateStudio.core.geometry import face_down,cross,unit
from BambuPlateStudio.core.layout import Bed,arrange,validate,footprint,process_clearance,auto_brim_reserve
from BambuPlateStudio.core.visual_edit import EditHistory,merge_onto,transfer_to_plate
from BambuPlateStudio.core.profiles import ProfileCatalog,discover,BEDS
from BambuPlateStudio.core.package3mf import NS

ROOT=Path(__file__).resolve().parent.parent


def load_fixture():
    path=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'test_artifacts'/'fusion_paper_petg_clearance.3mf'
    with zipfile.ZipFile(path) as z:
        model=ET.fromstring(z.read('3D/3dmodel.model'));config=ET.fromstring(z.read('Metadata/model_settings.config'))
        meta=json.loads(z.read('Metadata/BambuPlateStudio.json'))
    resources={o.get('id'):o for o in model.findall('c:resources/c:object',NS)}
    infos={o.get('id'):o for o in config.findall('object')};bodies=[]
    for obj in infos.values():
        for part in obj.findall('part'):
            values={e.get('key'):e.get('value') for e in part.findall('metadata')}
            uid=Path(values['source_file']).stem;color=meta['slots'][int(values['extruder'])-1]['color']
            mesh=resources[part.get('id')].find('c:mesh',NS)
            vertices=[tuple(float(v.get(k)) for k in ('x','y','z')) for v in mesh.findall('c:vertices/c:vertex',NS)]
            triangles=[tuple(int(t.get(k)) for k in ('v1','v2','v3')) for t in mesh.findall('c:triangles/c:triangle',NS)]
            b=Body(uid,values['name'],'真实网格 · 离线交互测试',color,vertices,triangles,face_colors={color:1});b.validate();bodies.append(b)
    session=Session(bodies);session.config.update(meta['configuration']);session.units={}
    session.color_profiles={s['color']:s['profile'] for s in meta['slots']}
    session.plates=[Plate(i,'测试盘') for i in range(1,meta['plates']+1)]
    for item in meta['units']:
        name=next(e.get('value') for e in infos[str(item['objectId'])].findall('metadata') if e.get('key')=='name')
        session.units[item['unit']]=PrintUnit(item['unit'],name,item['members'],tuple(tuple(r[:3]) for r in item['matrix'][:3]),orientation_label='已确认方向')
        low=item['bboxSceneMm'][0];origin=item['sceneOriginMm']
        session.placements[item['unit']]=Placement(item['unit'],item['plate'],low[0]-origin[0],low[1]-origin[1])
    return session


class Demo:
    def __init__(self):
        self.session=load_fixture();self.history=EditHistory();self.lock=threading.Lock();self.notices=[]
        self.orientation_preview=None;self.orientation_snapshot=None
        self.arrangement_preview=None;self.arrangement_snapshot=None
        self.preview_executor=ThreadPoolExecutor(max_workers=1)
        self.preview_job=None
        self.exe,roots=discover();self.catalog=ProfileCatalog(roots);self.bed=Bed.from_profile(self.catalog.resolve('machine',self.session.config['printer']))
        process=self.catalog.resolve('process',self.session.config['process'])
        self.session.config['printClearance']=process_clearance(process,self.session.config['enableSupport'])
        self.session.config['autoBrimReserve']=auto_brim_reserve(process)

    def state(self):
        from dataclasses import asdict
        s=self.session;units=[]
        for u in s.units.values():
            p=s.placements.get(u.uid)
            units.append({'uid':u.uid,'name':u.name,'rotation':u.rotation,'direction':u.orientation_label,'orientationLocked':u.orientation_locked,
                'members':[{'uid':m,'name':s.bodies[m].name,'path':s.bodies[m].component_path,'color':s.effective_color(m),'mixedFaces':False} for m in u.members],
                'size':u.geometry(s.bodies)[2],'placement':asdict(p) if p else None,'rect':footprint(s,p) if p else None})
        errors,warnings=validate(s,self.bed)
        opts=self.catalog.options(s.config['printer'])
        opts['machines']=[{'key':s.config['printer'],'name':'Bambu Lab P2S 0.4 nozzle','model':'Bambu Lab P2S','nozzle':'0.4'}]
        opts['beds']={k:v[0] for k,v in BEDS.items()}
        return {'document':'纸巾盒 · 离线交互测试','units':units,'plates':[asdict(p) for p in s.plates],
                'config':s.config,'bed':asdict(self.bed),'profiles':opts,'errors':errors,'warnings':warnings,
                'colorProfiles':s.color_profiles,'notices':self.notices,'geometryRevision':1,'exe':self.exe,
                 'canUndo':bool(self.history.undo_stack),'canRedo':bool(self.history.redo_stack),'lastExport':None,
                 'orientationPreview':self.orientation_preview,'arrangementPreview':self.arrangement_preview,
                 'pendingPreview':self.pending_state()}

    def pending_state(self):
        if not self.preview_job:return None
        job=self.preview_job
        return {'token':job['token'],'kind':job['kind'],'scope':job['scope'],
                'elapsedSeconds':time.monotonic()-job['started']}

    def dispatch(self,action,data):
        s=self.session
        if action=='viewport_data':return {'revision':1,'bodies':[{'uid':b.uid,'vertices':b.vertices,'triangles':b.triangles} for b in s.bodies.values()]}
        if action in ('bootstrap','scan'):return self.state()
        if action=='preview_status':
            job=self.preview_job
            if not job or data.get('token')!=job['token']:raise ValueError('建议已失效')
            if not job['future'].done():return {'pendingPreview':self.pending_state()}
            self.preview_job=None
            proposal=job['future'].result()
            if s.rules()!=job['snapshot']:raise ValueError('规则已改变')
            proposal['token']=job['token'];proposal['scope']=job['scope']
            if job['kind']=='orientation_preview':
                self.orientation_preview=proposal;self.orientation_snapshot=job['snapshot']
            else:self.arrangement_preview=proposal;self.arrangement_snapshot=job['snapshot']
            return self.state()
        if action in ('orientation_preview','arrangement_preview') and data.get('background') is True:
            scope=data.get('scope','unit')
            if action=='orientation_preview':
                if scope=='unit':work,args=suggest,(s,data['unit'],self.catalog,self.exe)
                else:
                    numbers=[data['plate']] if scope=='current' else [p.index for p in s.plates if any(x.plate==p.index for x in s.placements.values())]
                    selected=[uid for uid in s.units if uid in s.placements and s.placements[uid].plate in numbers]
                    work,args=suggest_many,(s,selected,numbers,self.catalog,self.exe)
            else:
                numbers=[data['plate']] if scope=='current' else [p.index for p in s.plates if any(x.plate==p.index for x in s.placements.values())]
                work,args=suggest_positions,(s,numbers,self.catalog,self.exe)
            token=new_id()
            self.preview_job={'token':token,'kind':action,'scope':scope,'started':time.monotonic(),
                              'snapshot':self.history.snapshot(s),'future':self.preview_executor.submit(work,*args)}
            return {'pendingPreview':self.pending_state()}
        if action in ('undo','redo'):
            self.orientation_preview=None;self.arrangement_preview=None;self.history.restore(s,action=='undo');return self.state()
        before=self.history.snapshot(s);self.notices=[]
        try:
            if action=='orientation_preview':
                self.arrangement_preview=None
                scope=data.get('scope','unit')
                if scope=='unit':self.orientation_preview=suggest(s,data['unit'],self.catalog,self.exe)
                else:
                    numbers=[data['plate']] if scope=='current' else [p.index for p in s.plates if any(x.plate==p.index for x in s.placements.values())]
                    selected=[uid for uid in s.units if uid in s.placements and s.placements[uid].plate in numbers]
                    self.orientation_preview=suggest_many(s,selected,numbers,self.catalog,self.exe)
                    self.orientation_preview['scope']=scope
                self.orientation_preview['token']=new_id();self.orientation_snapshot=self.history.snapshot(s)
                return self.state()
            elif action=='orientation_cancel':self.orientation_preview=None;return self.state()
            elif action=='orientation_apply':
                if not self.orientation_preview or data['token']!=self.orientation_preview['token'] or s.rules()!=self.orientation_snapshot:raise ValueError('建议已过期')
                if self.orientation_preview.get('batch'):
                    if not self.orientation_preview['units']:raise ValueError('没有需要改变的朝向')
                    for uid,proposal in self.orientation_preview['units'].items():apply_rotation(s,uid,proposal['rotation'])
                else:apply_rotation(s,self.orientation_preview['unit'],self.orientation_preview['rotation'])
            elif action=='orientation_lock':s.units[data['unit']].orientation_locked=data['locked']
            elif action=='arrangement_preview':
                self.orientation_preview=None
                numbers=[data['plate']] if data['scope']=='current' else [p.index for p in s.plates if any(x.plate==p.index for x in s.placements.values())]
                self.arrangement_preview=suggest_positions(s,numbers,self.catalog,self.exe)
                self.arrangement_preview['token']=new_id();self.arrangement_preview['scope']=data['scope']
                self.arrangement_snapshot=self.history.snapshot(s)
                return self.state()
            elif action=='arrangement_cancel':self.arrangement_preview=None;return self.state()
            elif action=='arrangement_apply':
                if not self.arrangement_preview or data['token']!=self.arrangement_preview['token'] or s.rules()!=self.arrangement_snapshot:raise ValueError('建议已过期')
                apply_positions(s,self.arrangement_preview,data.get('acceptBambuSpacing') is True)
            elif action=='group_drop':merge_onto(s,data['source'],data['target'])
            elif action=='transfer_plate':transfer_to_plate(s,data['unit'],data['plate'],self.bed,data.get('confirmMixed') is True)
            elif action=='rename_unit':s.units[data['unit']].name=data['name']
            elif action=='ungroup':s.ungroup(data['unit'])
            elif action=='move':
                from BambuPlateStudio.core.inputs import placement_change
                p=s.placements[data['unit']];p.plate,p.x,p.y,p.angle=placement_change(data,{p.index for p in s.plates})
            elif action=='viewer_face':
                b=s.bodies[data['body']];points=[b.vertices[i] for i in b.triangles[data['triangle']]]
                normal=unit(cross([points[1][i]-points[0][i] for i in range(3)],[points[2][i]-points[0][i] for i in range(3)]))
                s.units[data['unit']].rotation=face_down(normal);s.units[data['unit']].orientation_label='离线三角面演示朝下'
                self.notices=['这里只验证界面选面交互；Fusion 中会进一步校验真实 BRep 平面。']
            elif action=='arrange':arrange(s,self.bed)
            elif action=='add_plate':s.plates.append(Plate(len(s.plates)+1))
            elif action=='delete_plate':
                index=data['plate'];assert not any(p.plate==index for p in s.placements.values())
                s.plates=[p for p in s.plates if p.index!=index]
                for p in s.plates:
                    if p.index>index:p.index-=1
                for p in s.placements.values():
                    if p.plate>index:p.plate-=1
            elif action=='body_color':s.color_overrides[data['body']]=data['color'].upper()
            elif action=='config':
                from BambuPlateStudio.core.inputs import config_change
                s.config=config_change(s.config,data);s.invalidate_layout()
            elif action=='color_profile':s.color_profiles[data['color']]=data['profile']
            elif action=='reset_units':s.reset_units()
            elif action in ('save_rules','highlight','export','pick_face'):
                self.notices=['离线预览不会控制 Fusion、保存规则、导出或打印。']
            else:raise ValueError('离线测试暂不执行：'+action)
        except Exception:
            s.apply_rules(before);raise
        self.history.commit(before,s)
        self.orientation_preview=None
        self.arrangement_preview=None
        return self.state()


DEMO=Demo()
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'ui'),**kwargs)
    def do_POST(self):
        if self.path!='/api':self.send_error(404);return
        if self.headers.get('Origin') not in (None,'http://127.0.0.1:8796','http://localhost:8796'):
            self.send_error(403);return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>100000:raise ValueError('请求过大')
            request=json.loads(self.rfile.read(length))
            with DEMO.lock:state=DEMO.dispatch(request['action'],request.get('data',{}))
            response={'ok':True,'state':state}
        except Exception as exc:response={'ok':False,'error':str(exc),'confirmation':getattr(exc,'confirmation',None)}
        data=json.dumps(response,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

if __name__=='__main__':
    print('Local visual test: http://127.0.0.1:8796/?demo=1',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8796),Handler).serve_forever()
