"""Reject invalid editor values before they can poison an otherwise valid session."""
import math
import re


def finite_number(value, label, minimum=None):
    if isinstance(value, bool):
        raise ValueError(label+'必须是数值。')
    try:
        number=float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(label+'必须是数值。') from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise ValueError(label+'超出有效范围。')
    return number


def color_hex(value):
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value.strip()):
        raise ValueError('颜色必须使用 #RRGGBB 格式。')
    return value.strip().upper()


def config_change(current, changes):
    candidate=dict(current)
    for key,value in changes.items():
        if key not in current:
            raise ValueError('未知配置项：'+key)
        if key in ('gap','margin','printClearance'):
            value=finite_number(value,key,0.)
        elif key == 'nozzle':
            number=finite_number(value,'喷嘴直径',0.)
            if number == 0:raise ValueError('喷嘴直径必须大于零。')
            value=str(number)
        elif isinstance(current[key],bool):
            if not isinstance(value,bool):raise ValueError(key+'必须是开关值。')
        else:
            if not isinstance(value,str) or not value.strip():raise ValueError(key+'不能为空。')
            value=value.strip()
        candidate[key]=value
    if candidate['refinement'] not in ('high','normal'):
        raise ValueError('不支持的网格质量。')
    return candidate


def placement_change(data, available_plates):
    plate=finite_number(data['plate'],'盘号',1.)
    if not plate.is_integer() or int(plate) not in available_plates:
        raise ValueError('指定盘号不存在，请先新增打印盘。')
    return (int(plate), finite_number(data['x'],'X 坐标'), finite_number(data['y'],'Y 坐标'),
            finite_number(data['angle'],'旋转角度'))
