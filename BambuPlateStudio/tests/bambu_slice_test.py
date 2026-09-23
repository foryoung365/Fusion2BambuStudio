"""Actual installed Bambu slicing test, isolated data directory, never sends prints."""
import argparse
import json
import subprocess
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from BambuPlateStudio.core.profiles import ProfileCatalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--load-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result_path = output/'slice_test.json'
    if result_path.exists():
        raise FileExistsError('Use a fresh test output directory.')
    command = [str(args.exe.resolve()), '--datadir', str(output/'user_data'),
               '--outputdir', str(output), '--orient', '0', '--arrange', '0',
               '--allow-multicolor-oneplate=0', '--export-3mf', 'sliced.gcode.3mf']
    with zipfile.ZipFile(args.project) as source:
        settings = json.loads(source.read('Metadata/project_settings.config'))
        if 'Metadata/BambuPlateStudio.json' in source.namelist():
            metadata = json.loads(source.read('Metadata/BambuPlateStudio.json'))
        else:
            metadata={'slots':[{'color':color,'profile':settings['filament_settings_id'][i]}
                               for i,color in enumerate(settings['filament_colour'])]}
        model_config = ET.fromstring(source.read('Metadata/model_settings.config'))
    catalog = ProfileCatalog([args.exe.parent/'resources'/'profiles'])
    machine = catalog.resolve('machine', settings['printer_settings_id'])
    process = catalog.resolve('process', settings['print_settings_id'])
    machine['curr_bed_type'] = process['curr_bed_type'] = settings['curr_bed_type']
    process['enable_support'] = settings['enable_support']
    slot_by_object = {o.get('id'): {int(m.get('value')) for part in o.findall('part')
                      for m in part.findall('metadata') if m.get('key') == 'extruder'}
                      for o in model_config.findall('object')}
    single_material_plates = True
    for plate in model_config.findall('plate'):
        used = set()
        for instance in plate.findall('model_instance'):
            oid = next(m.get('value') for m in instance.findall('metadata') if m.get('key') == 'object_id')
            used.update(slot_by_object[oid])
        single_material_plates &= len(used) <= 1
    if single_material_plates:
        process['enable_prime_tower'] = '0'
    else:
        command[command.index('--allow-multicolor-oneplate=0')]='--allow-multicolor-oneplate=1'
        process['enable_prime_tower']=settings.get('enable_prime_tower','1')
    for filename, data in [('machine.json', machine), ('process.json', process)]:
        (output/filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    filaments = []
    for index, slot in enumerate(metadata['slots']):
        filament = catalog.resolve('filament', slot['profile'])
        filament['filament_colour'] = filament['default_filament_colour'] = [slot['color']]
        path = output/f'filament_{index+1}.json'
        path.write_text(json.dumps(filament, ensure_ascii=False, indent=2), encoding='utf-8')
        filaments.append(str(path))
    command += ['--load-settings', str(output/'machine.json')+';'+str(output/'process.json'),
                '--load-filaments', ';'.join(filaments)]
    if not args.load_only:
        command += ['--slice', '0']
    command += [str(args.project.resolve())]
    started = time.monotonic()
    result = {'input':str(args.project.resolve()), 'command':command, 'noPrinterTransmission':True}
    try:
        completed = subprocess.run(command, cwd=output, capture_output=True, timeout=args.timeout,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result.update(returncode=completed.returncode, timedOut=False)
        (output/'stdout.txt').write_bytes(completed.stdout)
        (output/'stderr.txt').write_bytes(completed.stderr)
    except subprocess.TimeoutExpired as exc:
        result.update(returncode=None, timedOut=True)
        (output/'stdout.txt').write_bytes(exc.stdout or b'')
        (output/'stderr.txt').write_bytes(exc.stderr or b'')
    if (output/'result.json').exists():
        result['engineResult'] = json.loads((output/'result.json').read_text(encoding='utf-8-sig'))
    exported = output/'sliced.gcode.3mf'
    result['outputExists'] = exported.is_file()
    if exported.exists():
        with zipfile.ZipFile(exported) as archive:
            result['gcodeFiles'] = [n for n in archive.namelist() if n.endswith('.gcode')]
            result['gcodeBytes'] = {n:archive.getinfo(n).file_size for n in result['gcodeFiles']}
    result['elapsedSeconds'] = time.monotonic()-started
    result['loadOnly'] = args.load_only
    expected=[i+1 for i,p in enumerate(model_config.findall('plate')) if p.findall('model_instance')]
    result['expectedNonemptyPlates']=expected
    actual=sorted(int(Path(n).stem.split('_')[-1]) for n in result.get('gcodeFiles',[]))
    result['passed'] = result['returncode'] == 0 and result['outputExists'] and (args.load_only or actual==expected)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
