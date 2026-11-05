# Local Development Guide

This guide helps you set up a local development environment to test and modify the AI chat completion application. First [deploy the Azure resources](deployment.md#deploy-from-this-folder).

## Prerequisites

- Python 3.13 (matching App Service)
- [Node.js](https://nodejs.org/) 22 LTS with npm
- An Azure deployment of the application (completed via `azd up`)

## Environment Setup

### 1. Python Environment

Create a [Python virtual environment](https://docs.python.org/3/tutorial/venv.html#creating-virtual-environments) and activate it:

**On Windows:**
```shell
python -m venv .venv
.venv\scripts\activate
```

**On Linux:**
```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

Navigate to the `src` directory and install Python packages:

```shell
cd src
python -m pip install -r requirements.txt
```

### 3. Frontend Setup

From the repository root, build the frontend with the same hook used for deployment:

```shell
python scripts/package_app.py
```

### 4. Environment Configuration

From the repository root, run `.\scripts\write_env.ps1` on Windows or
`bash scripts/write_env.sh` on Linux/macOS to write `src/.env` from `azd` outputs.
Sign in using `azd auth login`. Never commit `.env`.

## Running the Development Server

### 1. Build Frontend (Optional)

If you have changes in `src/frontend`, build the React application:

```shell
cd src/frontend
pnpm build
```

The build output will be placed in the `../api/static/react` directory, where the backend can serve it.

### 2. Start the Server

Run the local development server:

```shell
cd src
python -m uvicorn "api.main:create_app" --factory --reload
```

### 3. Access the Application

Click '<http://127.0.0.1:8000>' in the terminal, which should open a new tab in the browser. Enter your message in the box to test the chat completion.

## Frontend Development and Customization

If you want to modify the frontend application, the key component to understand is `src/frontend/src/components/agents/AgentPreview.tsx`. This component handles:

- **Backend Communication**: Contains the main logic for calling the backend API endpoints
- **Message Handling**: Manages the flow of user messages and chat responses
- **UI State Management**: Controls the display of conversation history and loading states

### Key Areas for Customization

- **Chat Interaction Flow**: Modify how users interact with the chat by updating the message handling logic in `AgentPreview.tsx`
- **UI Components**: Customize the chat interface, message bubbles, and response formatting
- **API Integration**: Extend or modify the backend communication patterns established in this component

### Development Workflow

1. Make changes to React components in `src/frontend/src/`
2. Run `pnpm build` to compile the frontend
3. The build output is automatically placed in `../api/static/react` for the backend to serve
4. Restart the local server to see your changes

Start with `AgentPreview.tsx` to understand how the frontend communicates with the backend and how messages are populated in the UI.

## Search Index and RAG Customization

This application uses Azure AI Search to provide Retrieval-Augmented Generation (RAG) capabilities. The system prompts the chat completion model with relevant context retrieved from a search index.

### How RAG Works in This Application

1. **Pre-computed Embeddings**: The application uses pre-computed embeddings stored in `src/api/data/embeddings.csv`
2. **Search Index Creation**: On startup, `gunicorn.conf.py` creates an Azure AI Search index and uploads the embeddings
3. **Query-time Search**: When users ask questions, the system searches for relevant context and includes it in the prompt
4. **Chat Completion**: The chat completion model responds using both the user's message and the retrieved context

### Updating the Knowledge Base

To update the knowledge base that the RAG system uses:

#### Modifying the Embeddings Data

1. **Update the CSV**: Modify `src/api/data/embeddings.csv` with your new data
2. **CSV Format**: The file should contain pre-computed embeddings and associated text content
3. **Restart or Redeploy**: The search index is only created once at startup, so you need to:
   - Delete the existing search index in Azure AI Search, then restart the application, OR
   - Restart the App Service web app after deleting the index to seed it again.

#### Important Notes About Data Updates

- **One-time Upload**: The embeddings are only uploaded when the search index is first created
- **Manual Index Management**: Code redeployment does not recreate or overwrite an existing search index.
- **Local Windows RAG**: Uvicorn's application lifespan creates the index but does not seed the CSV. Deploy once to populate sample data, or upload data to the index separately. Gunicorn's seeding hook runs on Linux App Service.
- **No File Directory**: This application does not use individual files from a `src/files/` directory
- **CSV Only**: The RAG system exclusively uses the `embeddings.csv` file for its knowledge base

### Customizing the RAG Behavior

#### Search Configuration
- Modify the search logic in `SearchIndexManager` class (`src/api/search_index_manager.py`)
- Adjust search parameters, scoring, and result filtering

#### Prompt Engineering
- Update the RAG prompt template in `src/api/routes.py` (around line 115)
- Customize how retrieved context is formatted and presented to the model

#### Model Configuration
- Change the chat completion model via the `AZURE_AI_CHAT_DEPLOYMENT_NAME` environment variable
- Adjust embedding model via the `AZURE_AI_EMBED_DEPLOYMENT_NAME` environment variable
