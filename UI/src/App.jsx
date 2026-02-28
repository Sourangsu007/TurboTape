import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import AnalyzePage from './pages/AnalyzePage';
import CoreAnalysisPage from './pages/CoreAnalysisPage';
import './index.css';

function App() {
  return (
    <Router>
      <div className="main-app">
        <Routes>
          <Route path="/" element={<Navigate to="/analyze" replace />} />
          <Route path="/analyze" element={<CoreAnalysisPage />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
