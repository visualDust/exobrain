def singleton(class_):
    """decorator to make a class a singleton

    usage:
        @singleton
        class MyClass:
            pass
    """

    class class_w(class_):
        _instance = None

        def __new__(cls, *args, **kwargs):  # noqa: ARG001
            if cls._instance is None:
                cls._instance = super(class_w, cls).__new__(cls)
            return cls._instance

        def __init__(self, *args, **kwargs):
            if not hasattr(self, "_initialized"):
                super(class_w, self).__init__(*args, **kwargs)
                self._initialized = True

    return class_w


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]
