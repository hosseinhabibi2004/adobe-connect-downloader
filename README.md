# Adobe Connect Downloader

A FastAPI-based web application that allows users to download and convert Adobe Connect meeting sessions into `.mkv` video files. It features real-time progress tracking via Server-Sent Events (SSE) and a simple history management system.

## Features

- **Download Meetings**: Fetches session data (videos, audio, slides) from Adobe Connect.
- **Conversion**: Converts the downloaded data into a single `.mkv` file.
- **Real-time Updates**: Progress updates are streamed to the frontend using SSE, so no page refresh is needed.
- **Download History**: Keeps track of recent conversions (stored in Redis) and cleans up expired jobs.
- **Persian UI**: The interface is in Persian (Farsi) with RTL layout support.

## Prerequisites

Before running this application, ensure you have the following installed:

1. **Python 3.14+ & uv**
2. **Redis**: The application requires Redis to store job status and history.

## Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/hosseinhabibi2004/adobe-connect-downloader.git
   cd adobe-connect-downloader
   ```

2. **Create a virtual environment**:

   ```bash
   uv venv
   ```

3. **Install dependencies**:

   ```bash
   uv sync
   ```

4. **Ensure Redis is running**:

   ```bash
   redis-server
   ```

## Configuration

The application uses environment variables for configuration. You can set these in your `.env` file or export them in your shell.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `REDIS_HOST` | Redis host address | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_DB` | Redis database number | `0` |
| `REDIS_PASSWORD` | Redis password (if set) | `None` |
| `BASE_DIR` | Base directory of the project | Current directory |
| `OUTPUT_DIR` | Directory for output `.mkv` files | `./output` |
| `TEMP_DIR` | Directory for temporary files | `./temp` |
| `TIMEZONE` | Timezone for timestamps | `Asia/Tehran` |

## Usage

1. **Start the Server**:

   ```bash
   uvicorn src.app:app --reload
   ```

2. **Access the Application**:
   Open your browser and navigate to:

   ```txt
   http://127.0.0.1:8000/
   ```

3. **Download a Meeting**:
   - Paste the Adobe Connect meeting URL (e.g., `https://example.com/XXXXXXX/?session=...`) into the input field.
   - Click Convert Meeting.
   - Monitor the progress bar and status messages in real-time.
   - Once finished, a download link will appear. Click it to download the `.mkv` file.

4. **View History**:
   The Recent Conversions section at the bottom shows the status of recent jobs.

## License

MIT License. See `LICENSE` file for details.

> Made with 💜 for her.
