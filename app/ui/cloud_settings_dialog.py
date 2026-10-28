from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QLineEdit,QPushButton,QMessageBox

class CloudSettingsDialog(QDialog):
    def __init__(self,controller,parent=None):
        super().__init__(parent);self.controller=controller;self.setWindowTitle('Cloud bridge');self.setMinimumWidth(440)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Cloud commands sync to this computer while Site Task AI is running.'))
        self.status=QLabel(controller.status);layout.addWidget(self.status);controller.status_changed.connect(self.status.setText)
        form=QFormLayout();self.origin=QLineEdit();self.origin.setPlaceholderText('https://your-worker.example.com')
        self.token=QLineEdit();self.token.setEchoMode(QLineEdit.EchoMode.Password);self.token.setPlaceholderText('Paste bridge credential; stored in Windows Credential Manager')
        try:self.origin.setText(controller.config().get('origin',''))
        except Exception:pass
        form.addRow('Server',self.origin);form.addRow('Credential',self.token);layout.addLayout(form)
        info=QLabel('Database ID: '+controller.store.identity()['db_id']);info.setWordWrap(True);layout.addWidget(info)
        connect=QPushButton('Save and connect');connect.clicked.connect(self.connect_bridge);layout.addWidget(connect)
        pause=QPushButton('Pause cloud connection');pause.clicked.connect(controller.pause);layout.addWidget(pause)
        recover=QPushButton('Reconcile after restoring a backup');recover.clicked.connect(self.recover);layout.addWidget(recover)
        mapping=QPushButton('Review conflicting task identities');mapping.clicked.connect(self.map_conflicts);layout.addWidget(mapping)
        close=QPushButton('Close');close.clicked.connect(self.accept);layout.addWidget(close)
    def connect_bridge(self):
        try:self.controller.configure(self.origin.text().strip(),self.token.text().strip());self.token.clear()
        except Exception as e:QMessageBox.warning(self,'Cloud bridge','Unable to connect: '+type(e).__name__+'. Check the address and credential.')

    def recover(self):
        answer=QMessageBox.question(self,'Reconcile restored database',
            'This will quarantine old cloud commands, preserve known completion/deletion and expiry information, and rebuild identity counters. '
            'Tasks with reused identities or permanent-deletion conflicts require manual mapping and will keep synchronization blocked. Continue?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer==QMessageBox.StandardButton.Yes:
            try:self.controller.recover()
            except Exception as e:QMessageBox.warning(self,'Cloud bridge','Recovery remains blocked: '+type(e).__name__)

    def map_conflicts(self):
        from app.services.local_recovery import conflict_plan,apply_confirmed_mapping
        controller=self.controller
        if controller.status!='manual_fork_mapping_required' or not controller.recovery:
            QMessageBox.information(self,'Recovery mapping','Run reconciliation first. No identity conflict is ready for review.');return
        plan=conflict_plan(controller.store.database,controller.recovery_items)
        if not plan:return
        dialog=QMessageBox(self);dialog.setWindowTitle('Review local identity mapping')
        dialog.setText(f'{len(plan)} local task(s) conflict with previous cloud identities. Preserve their content as new local tasks?')
        dialog.setInformativeText('Each listed task receives a fresh ID above all previous cloud IDs. Managed references are cleared. '
            'The old local identities are permanently removed and leave tombstones. Other tasks are unchanged.')
        dialog.setText(dialog.text()+'\n\n'+'\n'.join(f"#{p['task_id']}: {p['title']} → new local identity" for p in plan))
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No);dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec()==QMessageBox.StandardButton.Yes:
            try:
                apply_confirmed_mapping(controller.store.repository,plan,controller.recovery['max_task_id'])
                controller.queue.changed();controller.recover()
            except Exception as e:QMessageBox.warning(self,'Recovery mapping','Mapping was not completed: '+type(e).__name__)
