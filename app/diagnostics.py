"""Explicit packaged-runtime test; all task writes use a disposable temporary DB."""
def self_test(arguments):
    import argparse,json,tempfile,traceback
    from pathlib import Path
    from datetime import date
    from PySide6.QtCore import QTimer,QEventLoop,QUrl
    from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
    from app.application import create_application
    from app.database.connection import Database
    from app.database.task_repository import TaskRepository
    from app.models.task import Task
    from app.services.settings_service import SettingsService
    from app.services.cloud_store import CloudStore
    from app.ui.main_widget import MainWidget
    from app.ui.cloud_settings_dialog import CloudSettingsDialog
    from app.utils.paths import AppPaths
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--report',required=True,type=Path);p.add_argument('--https-origin')
    args=p.parse_args(arguments);report={'passed':False,'checks':[]};window=None
    try:
        application=create_application(['SiteTaskAI-self-test'])
        if application.platformName()=='offscreen':
            from PySide6.QtGui import QFontDatabase,QFont
            font=Path('C:/Windows/Fonts/segoeui.ttf')
            if font.exists():
                QFontDatabase.addApplicationFont(str(font));application.setFont(QFont('Segoe UI',10))
        with tempfile.TemporaryDirectory(prefix='sitetask-runtime-test-') as temporary:
            paths=AppPaths(Path(temporary));repo=TaskRepository(Database(paths.database_file))
            task=repo.create_task(Task(title='Packaged runtime self-test',due_date=date.today()))
            assert repo.complete_task(task.id).status=='completed'
            assert repo.restore_task(task.id).status=='pending'
            assert repo.soft_delete_task(task.id).deleted_at
            assert repo.undelete_task(task.id).deleted_at is None
            snapshot=CloudStore(repo).snapshot();assert len(snapshot['items'])==1
            report['checks'].extend(['schema6','create','complete','reopen','soft_delete','restore','cloud_snapshot'])
            window=MainWidget(repository=repo,settings_service=SettingsService(paths));window.show();application.processEvents()
            args.report.parent.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(args.report.with_suffix('.widget.png')))
            dialog=CloudSettingsDialog(window.cloud_bridge,window);dialog.show();application.processEvents()
            dialog.grab().save(str(args.report.with_suffix('.settings.png')));dialog.close()
            report['checks'].extend(['widget_render','cloud_settings_render'])
            if args.https_origin:
                from app.services.cloud_network import validate_origin,configure_tls_backend
                origin=validate_origin(args.https_origin)
                assert configure_tls_backend()
                manager=QNetworkAccessManager();request=QNetworkRequest(QUrl(origin+'/v1/health'))
                request.setRawHeader(b'User-Agent',b'SiteTaskAI/1.3')
                request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
                reply=manager.get(request);loop=QEventLoop();reply.finished.connect(loop.quit)
                timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(reply.abort);timer.start(20000);loop.exec();timer.stop()
                status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                assert status==401,f'HTTPS authentication boundary returned {status}'
                reply.deleteLater();report['checks'].append('packaged_https_tls_and_auth_boundary')
            window.local_queue_timer.stop();window.cloud_bridge.stop();window.local_queue.close();window._force_exit=True;window.close();application.processEvents()
            report['passed']=True
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1
