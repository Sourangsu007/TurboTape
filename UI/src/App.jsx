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
          <Route path="/" element={<Navigate to="/core" replace />} />
          <Route path="/core" element={<CoreAnalysisPage />} />
          <Route path="/analyze" element={<AnalyzePage />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
