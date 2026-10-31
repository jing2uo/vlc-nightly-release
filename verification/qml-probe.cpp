#include <QGuiApplication>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QDebug>
#include <QQuickWindow>
#include <QQuickItem>
#include <QTimer>
int main(int argc,char **argv) {
    QGuiApplication app(argc,argv);QQmlEngine engine;QQmlComponent component(&engine);
    component.setData(R"(import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import QtQml.Models
import QtQml.WorkerScript
Item { ColumnLayout { Button { text: "QML verification" } } })",QUrl());
    QObject *object=component.create();
    if(!object){qCritical()<<component.errors();return 1;}
    if(app.arguments().contains("--window")) {
        QQuickWindow window;window.resize(320,200);
        qobject_cast<QQuickItem *>(object)->setParentItem(window.contentItem());
        window.show();QTimer::singleShot(2000,&app,&QCoreApplication::quit);
        int status=app.exec();delete object;return status;
    }
    delete object;qInfo()<<"Qt/QML imports and component creation PASS";return 0;
}
