# XChat - Xebia AI Assistant

XChat is a cutting-edge AI assistant platform that serves as a centralized hub for Xebia's diverse suite of specialized bots. Leveraging Next.js 14 and advanced AI technologies, it offers enterprise-grade features including email classification, accelerators, and seamless chat-bot interactions. The platform combines robust authentication and intuitive user interface to deliver a powerful, unified experience for accessing Xebia's AI services. Built with Next.js 14, this application provides a unified experience across different AI services through a flexible adapter pattern.

## 🛠️ Tech Stack

- **Frontend**: Next.js 14, React 18, Redux Toolkit, TailwindCSS, Material UI
- **Authentication**: NextAuth.js with Azure AD provider
- **UI Components**: Custom components with Framer Motion animations
- **Visualization**: Plotly.js for data visualization
- **Voice Interaction**: React Speech Recognition and Vocode

## 🚀 Getting Started

### Prerequisites

- Node.js 18+
- npm or yarn
- Git

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/Xebia-Projects/xchat-app-ui.git
   cd xchat
   ```

2. Install dependencies:

   ```bash
   npm install
   # or
   yarn install
   ```

3. Create an `.env` file based on `.env.example`:

   ```bash
   cp .env.example .env
   ```

4. Update the environment variables in `.env` with your credentials

5. Start the development server:

   ```bash
   npm run dev
   # or
   yarn dev
   ```

6. Open [http://localhost:3000](http://localhost:3000) in your browser to see the application

## 🏗️ Project Structure

```
xchat/
├── src/
│   ├── app/                     # Next.js App Router
│   │   ├── api/                 # API routes
│   │   ├── auth/                # Authentication routes
│   │   └── main-app/            # Main application routes
│   │       ├── accelerators/    # Accelerators features
│   │       ├── bot/             # Bot conversation pages
│   │       ├── dashboard/       # Main dashboard
│   │       ├── email-classification/  # Email classification feature
│   │       └── user-management/ # User management feature
│   ├── components/              # React components
│   ├── hooks/                   # Custom React hooks
│   ├── icons/                   # Icon components/assets
│   ├── lib/                     # Utility libraries
│   ├── logger/                  # Logging utilities
│   ├── providers/               # Context providers
│   ├── store/                   # Redux or other state management
│   ├── style/                   # Styling (CSS, Tailwind, etc.)
│   ├── types/                   # TypeScript types
│   └── middleware.ts            # Middleware configuration
├── public/                      # Static assets
├── .env                         # Environment variables
├── .env.example                 # Example environment variables
├── next.config.js               # Next.js configuration
├── README.md                    # Project documentation
└── ...
```

## 🔌 Bot Adapter Pattern

XChat uses an adapter pattern to integrate with different LLM services:

> **Note**: This adapter pattern is specifically implemented for chat-bots and custom bots within the XChat ecosystem. Other features like email classification and accelerators follow different architectural patterns.

1. **BotAdapter Interface**: Defines the contract for all bot implementations
2. **BaseBotAdapter**: Provides common functionality for all adapters
3. **BotFactory**: Creates concrete adapter instances as needed
4. **BotService**: Manages communication with bots through their adapters
5. **API Routes**: Handles HTTP communication with external LLM services

This architecture makes it easy to add new AI services while maintaining a consistent interface.

## 🔑 Environment Variables

Create a `.env` file with the following variables:

```
# API Endpoints
MIDDLEWARE_URL=
XCHATGPT_API_KEY=

# Voice Bot Configuration
NEXT_PUBLIC_VOICE_BOT_API_URL=
NEXT_PUBLIC_VOICE_BOT_WS_URL=

# Authentication
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=

# Azure AD Configuration
NEXT_PUBLIC_AZURE_AD_CLIENT_ID=
NEXT_PUBLIC_AZURE_AD_CLIENT_SECRET=
NEXT_PUBLIC_AZURE_AD_TENANT_ID=
```

> **Note**: For production, use your own secure values and never commit your `.env` file to version control.
