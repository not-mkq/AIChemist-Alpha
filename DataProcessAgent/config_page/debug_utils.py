
import logging
from PyQt6.QtCore import QObject, QMetaMethod

logger = logging.getLogger("SignalTracer")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('[SIGNAL] %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

class SignalTracer(QObject):
    """
    调试工具：用于追踪 QObject 的信号发射。
    
    使用方法：
    tracer = SignalTracer()
    tracer.trace(some_widget, "WidgetName")
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.targets = []

    def trace(self, target: QObject, name: str = None):
        """
        开始追踪目标对象的信号。
        """
        if name is None:
            name = target.objectName() or str(target)
            
        meta = target.metaObject()
        for i in range(meta.methodCount()):
            method = meta.method(i)
            if method.methodType() == QMetaMethod.MethodType.Signal:
                # 获取信号签名
                signature = method.methodSignature().data().decode('utf-8')
                # 连接到一个通用的打印槽
                # 注意：PyQt6 中动态连接所有信号比较麻烦，这里我们使用简单的 lambda 闭包
                # 对于带有参数的信号，这种通用打印可能无法显示具体参数值，
                # 但能显示信号被触发了。
                self._connect_logger(target, signature, name)
                
        self.targets.append(target)
        logger.debug(f"Started tracing signals for: {name}")

    def _connect_logger(self, target, signal_name, obj_name):
        # 获取具体的信号对象
        # 这里的解析比较简略，主要用于调试
        try:
            signal_key = signal_name.split('(')[0]
            if hasattr(target, signal_key):
                signal = getattr(target, signal_key)
                # 使用 lambda 捕获上下文
                signal.connect(lambda *args: logger.debug(f"{obj_name} EMIT: {signal_name} | Args: {args}"))
        except Exception:
            pass
