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


def run_project(seed, job, catalog, executable, orient=False, arrange=False, timeout=60):
    """Run the installed engine in an isolated caller-owned temporary directory."""
    seed, job, executable = Path(seed), Path(job), Path(executable)
    if not executable.is_file():
        raise ValueError('未找到 Bambu Studio 可执行程序，不能验证完整项目导出。')
    with zipfile.ZipFile(seed) as archive:
        settings=json.loads(archive.read('Metadata/project_settings.config'))
        manifest=json.loads(archive.read('Metadata/BambuPlateStudio.json'))
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
             '--orient','1' if orient else '0','--arrange','1' if arrange else '0',
             '--allow-multicolor-oneplate=1' if arrange else '--allow-multicolor-oneplate=0',
             '--load-settings',str(job/'machine.json')+';'+str(job/'process.json'),
             '--load-filaments',';'.join(filenames),'--export-3mf','project.3mf',str(seed.resolve())]
    if arrange:command.insert(5,'--allow-rotations=0')
    started=time.monotonic()
    try:
        process_result=subprocess.run(command,cwd=job,capture_output=True,timeout=timeout,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Bambu 处理超时，未应用结果；请检查 Bambu 安装与运行状态。') from exc
    native=job/'project.3mf'
    (job/'stdout.txt').write_bytes(process_result.stdout)
    (job/'stderr.txt').write_bytes(process_result.stderr)
    result=json.loads((job/'result.json').read_text(encoding='utf-8-sig')) if (job/'result.json').exists() else {}
    if process_result.returncode != 0 or not native.exists():
        raise RuntimeError('Bambu 处理失败：'+result.get('error_string',str(process_result.returncode)))
    return native,time.monotonic()-started


def export_native(seed, destination, catalog, executable, timeout=60, overwrite=False):
    seed,destination=Path(seed),Path(destination)
    if destination.suffix.lower() != '.3mf':
        raise ValueError('输出文件必须使用 .3mf 扩展名。')
    if destination.exists() and not overwrite:
        raise FileExistsError('输出文件已存在，请选择新文件名。')
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError('目标路径不是普通文件，不能覆盖。')
    original=destination.stat() if destination.exists() else None
    with zipfile.ZipFile(seed) as archive:
        manifest=json.loads(archive.read('Metadata/BambuPlateStudio.json'))
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='BambuPlateStudio_') as temporary:
        native,elapsed=run_project(seed,temporary,catalog,executable,timeout=timeout)
        fidelity=verify(seed,native)
        if overwrite:
            staged=None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent,prefix=destination.name+'.',suffix='.tmp',delete=False) as out,native.open('rb') as source:
                    staged=Path(out.name)
                    shutil.copyfileobj(source,out)
                    out.flush();os.fsync(out.fileno())
                checksum=hashlib.sha256(staged.read_bytes()).hexdigest()
                if original:
                    current=destination.stat()
                    if (current.st_ino,current.st_size,current.st_mtime_ns)!=(original.st_ino,original.st_size,original.st_mtime_ns):
                        raise RuntimeError('目标文件在导出期间发生变化，未覆盖；请重新选择。')
                os.replace(staged,destination)
            finally:
                if staged and staged.exists():staged.unlink()
        else:
            with destination.open('xb') as out,native.open('rb') as source:
                shutil.copyfileobj(source,out)
            checksum=hashlib.sha256(destination.read_bytes()).hexdigest()
        return {'path':str(destination.resolve()),'sha256':checksum,
                'nativeBambuReadWritePassed':True,'sliced':False,'bodies':fidelity['bodies'],
                'objects':fidelity['objects'],'plates':fidelity['plates'],
                'maxVertexErrorMm':fidelity['maxVertexErrorMm'],
                'warnings':manifest['warnings'],'elapsedSeconds':elapsed,
                'status':'native_bambu_export_and_geometry_verified_not_sliced'}
