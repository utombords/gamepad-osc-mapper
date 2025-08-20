import logging
import sys

DEFAULT_LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'

def setup_logging(level=DEFAULT_LOG_LEVEL):
    """Configures basic logging for the application."""
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove any existing handlers to avoid duplicate messages if this is called multiple times
    # (though it should ideally be called once at startup)
    if root_logger.hasHandlers():
        for handler in root_logger.handlers[:]: # Iterate over a copy
            root_logger.removeHandler(handler)
            handler.close() # Close handler to release resources

    # Create a console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # Create a formatter and set it for the handler
    formatter = logging.Formatter(LOG_FORMAT)
    console_handler.setFormatter(formatter)

    # Add the handler to the root logger
    root_logger.addHandler(console_handler)

    # You could also add a file handler here if desired:
    # file_handler = logging.FileHandler('app.log')
    # file_handler.setLevel(logging.DEBUG) # Or any other level
    # file_handler.setFormatter(formatter)
    # root_logger.addHandler(file_handler)

    logging.info("Root logging configured.")

if __name__ == '__main__':
    # Keep module self-test silent in production
    pass