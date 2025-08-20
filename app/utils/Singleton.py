'''
Singleton Metaclass Implementation
'''

class Singleton(type):
    """
    A metaclass that creates a Singleton base type when called.
    This means that any class using this metaclass will only have one instance.
    """
    _instances = {}

    def __call__(cls, *args, **kwargs):
        """
        Override the default call behavior. If an instance of this class
        doesn't exist, create it and store it. Otherwise, return the existing instance.
        """
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]

# Example Usage (for testing, not needed by other modules directly):
# if __name__ == '__main__':
#     class MyClass(metaclass=Singleton):
#         def __init__(self, data=None):
#             print(f"MyClass initialized with {data}")
#             self.data = data

#     a = MyClass("first")
#     b = MyClass("second") # This will not re-initialize, will return instance 'a'

#     print(f"a is b: {a is b}") # True
#     print(f"a.data: {a.data}")   # first
#     print(f"b.data: {b.data}")   # first (because b is the same instance as a) 