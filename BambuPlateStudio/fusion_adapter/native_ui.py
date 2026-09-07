"""Native Fusion GUI, usable without an embedded web-browser runtime."""
from pathlib import Path
import adsk.core
import adsk.fusion
from ..core.geometry import face_down


class NativeDialog:
    def __init__(self, command, controller, handlers):
        self.command, self.controller, self.handlers = command, controller, handlers
        self.fields, self.choices, self.active_uid = {}, {}, None
        self.updating = False
        command.okButtonText = '保存规则并关闭'
        command.isRepeatable = False
        command.isExecutedWhenPreEmpted = False
        inputs = command.commandInputs
        self.text(inputs, 'status', '', '请读取当前设计。', 3)
        settings = inputs.addTabCommandInput('settings_tab', '打印配置').children
        self.string(settings,'bambu_exe','Bambu 程序路径',controller.exe)
        self.button(settings,'load_installation','读取该安装位置的预设')
        self.drop(settings, 'printer', '打印机')
        self.string(settings, 'nozzle', '喷嘴直径 / mm', '0.4')
        self.drop(settings, 'bed', '打印板')
        self.drop(settings, 'process', '工艺')
        self.drop(settings, 'filament', '默认耗材')
        for key, title in [('gap','零件间距 / mm'),('margin','板边距 / mm')]:
            self.string(settings, key, title, '5')
        for key,title in [('allowZRotation','排盘允许绕 Z 轴旋转 90°'),('allowMixedPlates','允许手动混色盘'),
                          ('includeHidden','包括隐藏实体'),('enableSupport','启用支撑')]:
            self.fields[key] = settings.addBoolValueInput(key,title,True,'',bool(controller.session.config[key]))
        self.button(settings,'apply_config','应用配置 / 更新兼容预设')
        self.button(settings,'scan_model','读取当前设计')
        self.drop(settings,'color','模型颜色')
        self.drop(settings,'color_filament','为该颜色指定耗材')
        self.button(settings,'apply_color_profile','应用颜色耗材映射')
        grouping = inputs.addTabCommandInput('grouping_tab','打印组与方向').children
        self.drop(grouping,'members','多选打印单元',True)
        self.string(grouping,'group_name','新组名称','整体打印组')
        self.button(grouping,'group_units','组合所选单元（保留原装配）')
        self.drop(grouping,'unit','当前编辑单元')
        self.text(grouping,'unit_details','','',5)
        self.button(grouping,'ungroup_unit','解除当前整体')
        self.button(grouping,'reset_units','确认重建所有分组/方向规则')
        self.drop(grouping,'direction','朝下方向')
        self.fill('direction',[(v,n) for v,n in [('keep','保持当前已指定方向'),('original','恢复原始装配方向'),('top','顶面朝下 (+Z)'),
            ('bottom','底面朝下 (-Z)'),('front','前面朝下 (-Y)'),('back','后面朝下 (+Y)'),
            ('left','左面朝下 (-X)'),('right','右面朝下 (+X)')]],'keep')
        self.button(grouping,'apply_direction','应用方向')
        selection = grouping.addSelectionInput('face','或点选贴板面','请选择当前单元的平面')
        selection.addSelectionFilter('PlanarFaces');selection.setSelectionLimits(0,1)
        self.fields['face'] = selection
        self.button(grouping,'apply_face','使用所选平面朝下')
        self.drop(grouping,'body','整件颜色覆盖：选择成员')
        self.string(grouping,'body_hex','打印颜色 #RRGGBB','#808080')
        self.button(grouping,'apply_body_color','仅覆盖导出颜色')
        layout = inputs.addTabCommandInput('layout_tab','排盘与导出').children
        self.button(layout,'arrange_units','自动按色排盘')
        self.button(layout,'preview_all','在视图区预览全部盘')
        self.text(layout,'layout_details','','尚未排盘。',10)
        self.drop(layout,'edit_unit','移动打印单元')
        for key,title,value in [('plate','盘号','1'),('x','X / mm','0'),('y','Y / mm','0'),('angle','板面旋转 / °','0')]:
            self.string(layout,key,title,value)
        self.button(layout,'move_unit','应用手动盘位')
        self.button(layout,'preview_plate','在视图区预览指定盘')
        self.button(layout,'clear_preview','清除预览（不删除实体）')
        self.button(layout,'add_plate','新增空盘')
        self.button(layout,'delete_plate','删除指定空盘')
        self.button(layout,'export_project','导出一个完整 3MF')
        self.text(layout,'safety','','只导出文件，不启动打印。红色/错误提示必须处理；网格警告不自动修复。',3)
        changed = Changed(self)
        command.inputChanged.add(changed);handlers.append(changed)
        executed = Executed(self)
        command.execute.add(executed);handlers.append(executed)
        self.refresh(True)

    def drop(self,parent,key,title,multi=False):
        style = adsk.core.DropDownStyles.CheckBoxDropDownStyle if multi else adsk.core.DropDownStyles.TextListDropDownStyle
        self.fields[key] = parent.addDropDownCommandInput(key,title,style)

    def text(self,parent,key,title,value,rows):
        self.fields[key] = parent.addTextBoxCommandInput(key,title,'',rows,True)
        self.fields[key].text = value

    def string(self,parent,key,title,value):
        self.fields[key] = parent.addStringValueInput(key,title,value)

    def button(self,parent,key,title):
        resources = str(Path(__file__).resolve().parent.parent/'resources'/'action')
        self.fields[key] = parent.addBoolValueInput(key,title,False,resources,False)

    def fill(self,key,rows,value=None):
        rows=list(rows);self.choices[key]=[v for v,n in rows]
        field=self.fields[key];field.listItems.clear()
        for index,(v,name) in enumerate(rows):field.listItems.add(name,v==value or(value is None and index==0))

    def selected(self,key):
        item=self.fields[key].selectedItem
        if item is None:raise ValueError('请选择：'+self.fields[key].name)
        value=self.choices[key][item.index]
        if value is None:raise ValueError('请选择兼容预设：'+self.fields[key].name)
        return value

    def selected_or_none(self,key):
        try:return self.selected(key)
        except (ValueError,KeyError,IndexError):return None

    def fill_presets(self,key,rows,value):
        chosen=next((p['key'] for p in rows if p['key']==value or p['name']==value),None)
        items=[(p['key'],p['name']) for p in rows]
        if chosen is None:items.insert(0,(None,'请选择兼容预设'))
        self.fill(key,items,chosen)

    def sync_color_profile(self):
        color=self.selected_or_none('color')
        cfg=self.controller.session.config
        profile=self.controller.session.color_profiles.get(color,cfg['filament'])
        self.fill_presets('color_filament',self.catalog_state['filaments'],profile)

    def sync_body_color(self):
        body=self.selected_or_none('body')
        if body:self.fields['body_hex'].value=self.controller.session.effective_color(body)

    def refresh(self,profiles=False):
        self.updating=True
        try:
            c=self.controller;state=c.state();cfg=c.session.config
            old_color=self.selected_or_none('color')
            if profiles:
                self.catalog_state=c.profile_state()
                for key,source in [('printer','machines'),('process','processes'),('filament','filaments')]:
                    rows=self.catalog_state[source]
                    self.fill_presets(key,rows,cfg[key])
                self.fill('bed',self.catalog_state['beds'].items(),cfg['bed'])
                for key in ['gap','margin','nozzle']:self.fields[key].value=str(cfg[key])
            for key in ['allowZRotation','allowMixedPlates','includeHidden','enableSupport']:self.fields[key].value=bool(cfg[key])
            units=list(c.session.units.values())
            if self.active_uid not in c.session.units:self.active_uid=units[0].uid if units else None
            rows=[(u.uid,f'{i+1}. {u.name} ({len(u.members)} 件)') for i,u in enumerate(units)]
            self.fill('unit',rows,self.active_uid);self.fill('edit_unit',rows,self.active_uid)
            self.fill('members',rows,'')
            colors=sorted({c.session.effective_color(uid) for uid in c.session.bodies})
            self.fill('color',[(v,v) for v in colors],old_color if old_color in colors else None)
            self.sync_color_profile()
            if self.active_uid:
                u=c.session.units[self.active_uid]
                self.fields['direction'].listItems.item(0).isSelected=True
                self.fields['unit_details'].text=u.name+'\n'+u.orientation_label+'\n'+'\n'.join(
                    c.session.bodies[m].component_path+' / '+c.session.bodies[m].name for m in u.members)
                self.fill('body',[(m,c.session.bodies[m].name+' '+c.session.effective_color(m)) for m in u.members])
                self.fields['body_hex'].value=c.session.effective_color(u.members[0])
                p=c.session.placements.get(u.uid)
                if p:
                    for key in ['plate','x','y','angle']:self.fields[key].value=str(getattr(p,key))
            lines=[]
            for plate in c.session.plates:
                lines.append(f'第 {plate.index} 盘')
                for p in c.session.placements.values():
                    if p.plate==plate.index:lines.append(f'  {c.session.units[p.unit].name}  X={p.x:.1f}, Y={p.y:.1f}, Z旋转={p.angle:g}°')
            self.fields['layout_details'].text='\n'.join(lines) or '尚未排盘。'
            self.fields['status'].text=f'{state["document"]} · {len(c.session.bodies)} 实体 / {len(units)} 单元 / {len(c.session.plates)} 盘\n'+'\n'.join(state['errors']+state['warnings']+state['notices'])
        finally:self.updating=False

    def action(self,key):
        c=self.controller;f=self.fields
        if key=='load_installation':
            c.dispatch('installation',{'executable':f['bambu_exe'].value.strip()})
        elif key=='apply_config':
            printer=self.selected('printer');nozzle=str(float(f['nozzle'].value.strip()))
            machine=c.catalog.resolve('machine',printer)
            if machine['nozzle_diameter'][0]!=nozzle:
                match=next((m for m in self.catalog_state['machines'] if m['model']==machine['printer_model'] and m['nozzle']==nozzle),None)
                if not match:raise ValueError('该机型不存在指定喷嘴的预设。')
                printer=match['key']
            data={k:self.selected(k) for k in ['bed','process','filament']}
            data.update(printer=printer,nozzle=nozzle,gap=float(f['gap'].value),margin=float(f['margin'].value))
            data.update({k:f[k].value for k in ['allowZRotation','allowMixedPlates','includeHidden','enableSupport']})
            c.dispatch('config',data)
        elif key=='scan_model':c.dispatch('scan',{})
        elif key=='apply_color_profile':c.dispatch('color_profile',{'color':self.selected('color'),'profile':self.selected('color_filament')})
        elif key=='group_units':
            selected=[self.choices['members'][i] for i in range(f['members'].listItems.count) if f['members'].listItems.item(i).isSelected]
            before=set(c.session.units)
            c.dispatch('group',{'units':selected,'name':f['group_name'].value})
            self.active_uid=next(iter(set(c.session.units)-before))
        elif key=='ungroup_unit':c.dispatch('ungroup',{'unit':self.selected('unit')})
        elif key=='reset_units':
            ui=adsk.core.Application.get().userInterface
            answer=ui.messageBox('将清除当前打印分组和贴板方向，保留原设计几何。是否确认重新指定？',
                '重建打印规则',adsk.core.MessageBoxButtonTypes.YesNoButtonType)
            if answer==adsk.core.DialogResults.DialogYes:c.dispatch('reset_units',{})
        elif key=='apply_direction':c.dispatch('direction',{'unit':self.selected('unit'),'mode':self.selected('direction')})
        elif key=='apply_face':
            c.assert_document()
            if f['face'].selectionCount!=1:raise ValueError('请先选择一个平面。')
            unit=c.session.units[self.selected('unit')]
            face=adsk.fusion.BRepFace.cast(f['face'].selection(0).entity)
            unit.rotation=face_down(c.source.normal_for_face(face,unit,c.session))
            unit.face_token=face.entityToken;unit.orientation_label='所选平面朝下';unit.orientation_valid=True;c.session.invalidate_layout()
        elif key=='apply_body_color':c.dispatch('body_color',{'body':self.selected('body'),'color':f['body_hex'].value.strip()})
        elif key=='arrange_units':c.dispatch('arrange',{})
        elif key=='preview_all':c.show_preview()
        elif key=='preview_plate':c.show_preview(int(f['plate'].value))
        elif key=='clear_preview':c.clear_preview()
        elif key=='move_unit':c.dispatch('move',{'unit':self.selected('edit_unit'),'plate':int(f['plate'].value),'x':float(f['x'].value),'y':float(f['y'].value),'angle':float(f['angle'].value)})
        elif key=='add_plate':c.dispatch('add_plate',{})
        elif key=='delete_plate':c.dispatch('delete_plate',{'plate':int(f['plate'].value)})
        elif key=='export_project':c.dispatch('export',{})
        self.refresh(key in ['apply_config','scan_model','load_installation'])


class Changed(adsk.core.InputChangedEventHandler):
    def __init__(self,dialog):super().__init__();self.dialog=dialog
    def notify(self,args):
        d=self.dialog
        if d.updating:return
        try:
            key=args.input.id
            if key in ['unit','edit_unit']:
                d.active_uid=d.selected(key);d.refresh()
            elif key in ['color','body']:
                d.updating=True
                try:
                    if key=='color':d.sync_color_profile()
                    else:d.sync_body_color()
                finally:d.updating=False
            elif isinstance(args.input,adsk.core.BoolValueCommandInput) and not args.input.isCheckBox and args.input.value:
                d.updating=True;args.input.value=False;d.updating=False
                d.action(key)
        except Exception as exc:
            d.fields['status'].text='操作未完成：'+str(exc)


class Executed(adsk.core.CommandEventHandler):
    def __init__(self,dialog):super().__init__();self.dialog=dialog
    def notify(self,args):
        try:self.dialog.controller.dispatch('save_rules',{})
        except Exception as exc:args.executeFailed=True;args.executeFailedMessage=str(exc)
