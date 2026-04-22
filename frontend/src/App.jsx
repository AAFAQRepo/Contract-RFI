import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { ProjectProvider } from './contexts/ProjectContext'
import ProtectedRoute from './components/common/ProtectedRoute'
import AppLayout from './layouts/AppLayout'
import AuthLayout from './layouts/AuthLayout'
import ChatPage from './pages/ChatPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import OnboardingWizard from './pages/onboarding/OnboardingWizard'
import './index.css'
import './App.css'

export default function App() {
  return (
    <AuthProvider>
      <ProjectProvider>
        <BrowserRouter>
          <Routes>
            {/* Public Routes */}
            <Route element={<AuthLayout />}>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            </Route>

            {/* Protected Routes */}
            <Route element={<ProtectedRoute />}>
              <Route path="/onboarding" element={<OnboardingWizard />} />
            </Route>

            <Route element={<ProtectedRoute requireOnboarded />}>
              <Route element={<AppLayout />}>
                <Route path="/" element={<ChatPage />} />
                <Route path="/chat" element={<ChatPage />} />
                {/* Future: /documents, /dashboard, /settings */}
              </Route>
            </Route>

            {/* Fallback */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ProjectProvider>
    </AuthProvider>
  )
}
