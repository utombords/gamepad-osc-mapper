# Main application entry point, Flask app creation, service orchestration
import logging
import sys
import os
import time # Import time
import threading
import argparse
from flask import Flask
from flask_socketio import SocketIO

# Adjust the Python path to include the root directory of the application
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
# Add the parent directory (which should be 'gamepad_osc_mapper') to sys.path
# to allow imports like from app.services.web_service import WebService
# This is often needed when running module with -m from a different CWD or for some IDEs.
# However, if 'gamepad_osc_mapper' is the project root and you run `python -m app.main` from there,
# direct imports like `from services.web_service...` might work if app is implicitly a package.
# To be safe and explicit:
sys.path.insert(0, PARENT_DIR)

# Now that the path is adjusted, we can use absolute imports from the project root perspective
from app.services.web_service import WebService
from app.services.config_service import ConfigService
from app.services.input_service import InputService # Import InputService separately
from app.services.channel_processing_service import ChannelProcessingService
from app.services.osc_service import OSCService
from app.utils.logging_config import setup_logging, DEFAULT_LOG_LEVEL
from app.utils.runtime_paths import get_base_path, load_or_create_secret_key

# Logger setup will be done in main after parsing args
## logging configured later via setup_logging
logger = logging.getLogger(__name__) # Get logger instance, setup_logging will configure it

## No startup banner; rely on structured logging

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Gamepad OSC Mapper')
    parser.add_argument(
        '--log-level',
        default=logging.getLevelName(DEFAULT_LOG_LEVEL), # Use string name of default level
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Set the logging level (default: INFO)'
    )
    args = parser.parse_args()

    # Convert string log level to logging level integer
    numeric_log_level = getattr(logging, args.log_level.upper(), None)
    if not isinstance(numeric_log_level, int):
        raise ValueError(f'Invalid log level: {args.log_level}')

    setup_logging(level=numeric_log_level) # Pass the parsed level
    
    # Now that logging is configured, we can log the atexit registration
    # logger.info("Registered _main_py_atexit_diagnostics.") # No longer registering
    logger.info(f"Logging level set to: {args.log_level}")
    logger.info("Starting Gamepad OSC Mapper application...")

    # Initialize Flask app and SocketIO (frozen-safe paths)
    BASE_PATH = get_base_path()

    app = Flask(
        __name__,
        static_folder=os.path.join(BASE_PATH, 'static'),
        template_folder=os.path.join(BASE_PATH, 'templates')
    )

    app.config['SECRET_KEY'] = load_or_create_secret_key()

    # Choose async mode (standardize on threading for simplicity and reliability)
    selected_mode = 'threading'
    # Reduce noisy socket logs by default; enable via env SOCKETIO_LOGGERS=1 if needed
    enable_socketio_logs = os.environ.get('SOCKETIO_LOGGERS', '0') == '1'
    socketio = SocketIO(app, logger=enable_socketio_logs, engineio_logger=enable_socketio_logs, async_mode=selected_mode)

    # Initialize Services (Order can matter for dependencies)
    config_service = ConfigService() # No direct dependencies from other custom services in __init__
    
    # InputService depends on ConfigService and SocketIO (optional for emit)
    input_service = InputService(config_service_instance=config_service, socketio_instance=socketio)

    # OSCService depends on ConfigService 
    osc_service = OSCService(config_service_instance=config_service)

    # ChannelProcessingService depends on OSCService, InputService, ConfigService, and SocketIO
    channel_processing_service = ChannelProcessingService(
        config_service_instance=config_service,
        input_service_instance=input_service,
        socketio_instance=socketio,
        osc_service_instance=osc_service
    )
    # After ChannelProcessingService is created, set its instance on OSCService if needed by OSCService
    # This resolves a potential circular dependency if OSCService also needed ChannelProcessingService in its __init__
    if hasattr(osc_service, 'set_channel_processing_service'):
        osc_service.set_channel_processing_service(channel_processing_service)
    else:
        logger.warning("OSCService does not have 'set_channel_processing_service' method. Channel processing might not be fully integrated with OSC output.")


    # WebService depends on app, SocketIO, ConfigService, OSCService, InputService
    web_service = WebService(
        app_instance=app,
        socketio_instance=socketio,
        config_service_instance=config_service,
        osc_service_instance=osc_service,
        input_service_instance=input_service
        # Removed: channel_processing_service_instance=channel_processing_service
    )
    
    # Start the input polling thread from InputService
    input_service.start_polling()

    # Removed keep-alive thread; not required for threading mode

    # Start the Flask-SocketIO web server
    # Allowing 0.0.0.0 to make it accessible on the network
    # Debug mode should be False for production or when not actively debugging Flask itself
    host = config_service.get_web_settings().get('host', '127.0.0.1')
    port = config_service.get_web_settings().get('port', 5000)
    logger.info(f"Starting web server on {host}:{port}")
    
    try:
        # Run SocketIO in threading mode; disable Flask debug and reloader in production
        socketio.run(app, host=host, port=port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        logger.info("Application interrupted by user (KeyboardInterrupt).")
    except Exception as e:
        logger.error(f"An error occurred while running the web server: {e}", exc_info=True)
    finally:
        logger.info("Application shutting down...")
        if 'input_service' in locals() and input_service:
            input_service.stop_polling()
        if 'channel_processing_service' in locals() and channel_processing_service:
            channel_processing_service.stop_processing_loop()
        # Add any other cleanup tasks here
        logger.info("Application shutdown complete.") 