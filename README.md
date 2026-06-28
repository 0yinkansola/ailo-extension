# AILO Chrome Extension

AILO is a Chrome extension designed to enhance language immersion on YouTube by replacing the default recommendation feed with personalized, target-language content.

## Prerequisites

Before running the project, ensure you have:

* Google Chrome
* Python 3.10 or later
* Git (optional, for cloning the repository)

## Installation

### 1. Download the Project

Clone the repository:

```bash
git clone https://github.com/0yinkansola/ailo-extension.git
```

Or download the repository as a ZIP file from GitHub and extract it.

---

### 2. Install Backend Dependencies

Open a terminal inside the `backend` folder and install the required packages:

```bash
cd backend
pip install -r requirements.txt
```

---

### 3. Start the Backend

Run the backend server:

```bash
python app.py
```

Leave this terminal open while using the extension.

---

### 4. Load the Chrome Extension

1. Open Google Chrome.
2. Go to:

```
chrome://extensions
```

3. Enable **Developer mode** (top-right).
4. Click **Load unpacked**.
5. Select the **extension** folder from this project.
6. The AILO extension will now appear in your list of installed extensions.

---

### 5. Using the Extension

1. Ensure the backend server is running.
2. Open YouTube.
3. Activate the AILO extension if necessary.
4. The extension will communicate with the backend to generate personalized recommendations.

---

## Project Structure

```
ailo-extension/
│
├── backend/          # Python backend
├── extension/        # Chrome extension source files
├── data/             # Data files
└── README.md
```

## Notes

* The backend must be running before using the extension.
* If changes are made to the extension, click **Reload** on the extension card in `chrome://extensions` to apply them.
* This project is intended for local execution and demonstration purposes.
