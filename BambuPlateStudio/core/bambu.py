"""Native Bambu serialization, with explicit presets and no reorientation/packing."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from .bambu_validation import verify


def export_native(seed, destination, catalog, executable, timeout=60):
    seed, destination, executable = Path(seed), Path(destination), Path(executable)
    if destination.suffix.lower() != '.3mf':
        raise ValueError('输出文件必须使用 .3mf 扩展名。')
    if not executable.is_file():
        raise ValueError('未找到 Bambu Studio 可执行程序，不能验证完整项目导出。')
    if destination.exists():
        raise FileExistsError('输出文件已存在，请选择新文件名。')
    with zipfile.ZipFile(seed) as archive:
        settings=json.loads(archive.read('Metadata/project_settings.config'))
        manifest=json.loads(archive.read('Metadata/BambuPlateStudio.json'))
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='BambuPlateStudio_') as temporary:
        job=Path(temporary)
        if ';' in str(job):
            raise ValueError('Bambu 的预设路径列表不支持含分号的临时目录。')
        configuration=manifest.get('configuration',{})
        machine=catalog.resolve('machine',configuration.get('printer',settings['printer_settings_id']))
        process=catalog.resolve('process',configuration.get('process',settings['print_settings_id']))
        machine['curr_bed_type']=process['curr_bed_type']=settings['curr_bed_type']
        process['enable_support']=settings['enable_support']
        if 'enable_prime_tower' in settings:process['enable_prime_tower']=settings['enable_prime_tower']
        for filename,data in [('machine.json',machine),('process.json',process)]:
            (job/filename).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        filenames=[]
        for index,slot in enumerate(manifest['slots']):
            filament=catalog.resolve('filament',slot['profile'])
            filament['filament_colour']=filament['default_filament_colour']=[slot['color']]
            path=job/f'filament_{index+1}.json'
            path.write_text(json.dumps(filament,ensure_ascii=False,indent=2),encoding='utf-8')
            filenames.append(str(path))
        command=[str(executable), '--datadir',str(job/'user_data'),'--outputdir',str(job),
                 '--orient','0','--arrange','0','--allow-multicolor-oneplate=0',
                 '--load-settings',str(job/'machine.json')+';'+str(job/'process.json'),
                 '--load-filaments',';'.join(filenames),'--export-3mf','project.3mf',str(seed.resolve())]
        started=time.monotonic()
        try:
            process_result=subprocess.run(command,cwd=job,capture_output=True,timeout=timeout,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Bambu 原生导出超时，未生成正式项目；请检查 Bambu 安装与运行状态。') from exc
        native=job/'project.3mf'
        result=json.loads((job/'result.json').read_text(encoding='utf-8-sig')) if (job/'result.json').exists() else {}
        if process_result.returncode != 0 or not native.exists():
            raise RuntimeError('Bambu 原生导出失败：'+result.get('error_string',str(process_result.returncode)))
        fidelity=verify(seed,native)
        with destination.open('xb') as out,native.open('rb') as source:
            shutil.copyfileobj(source,out)
        return {'path':str(destination.resolve()),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                'nativeBambuReadWritePassed':True,'sliced':False,'bodies':fidelity['bodies'],
                'objects':fidelity['objects'],'plates':fidelity['plates'],
                'maxVertexErrorMm':fidelity['maxVertexErrorMm'],
                'warnings':manifest['warnings'],'elapsedSeconds':time.monotonic()-started,
                'status':'native_bambu_export_and_geometry_verified_not_sliced'}
