import React, { useState } from 'react';
import stockService from '../services/stockService';
import './AnalyzePage.css';

const AnalyzePage = () => {
    const [stockName, setStockName] = useState('');
    const [portfolioType, setPortfolioType] = useState('Core');
    const [purpose, setPurpose] = useState('buy');
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const handleSearch = async (e) => {
        e.preventDefault();
        if (!stockName.trim()) return;

        setLoading(true);
        setResult(null);
        setError(null);

        try {
            const data = await stockService.analyzeStock(stockName, portfolioType, purpose);
            setResult(data);
        } catch (err) {
            const errorDetail = err.response?.data?.detail
                ? (Array.isArray(err.response.data.detail)
                    ? err.response.data.detail.map(d => d.msg).join(', ')
                    : err.response.data.detail)
                : (err.message || 'Failed to analyze stock. Ensure backend is running.');
            setError(errorDetail);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="analyze-container">
            <div className="search-section">
                <h1 className="title">Stock <span>AI</span> Analyzer</h1>
                <p className="subtitle">Enter a stock name to perform a deep fundamental and trend analysis</p>

                <form onSubmit={handleSearch} className="search-form">
                    <div className="input-group">
                        <input
                            type="text"
                            placeholder="e.g. Reliance, AAPL, HDFC Bank..."
                            value={stockName}
                            onChange={(e) => setStockName(e.target.value)}
                            disabled={loading}
                            className="search-input"
                        />
                    </div>

                    <div className="options-group">
                        <select
                            value={portfolioType}
                            onChange={(e) => setPortfolioType(e.target.value)}
                            disabled={loading}
                            className="select-input"
                        >
                            <option value="Core">Core Portfolio</option>
                            <option value="Satellite">Satellite Portfolio</option>
                        </select>

                        <select
                            value={purpose}
                            onChange={(e) => setPurpose(e.target.value)}
                            disabled={loading}
                            className="select-input"
                        >
                            <option value="buy">Purpose: Buy</option>
                            <option value="add">Purpose: Add</option>
                            <option value="sell">Purpose: Sell</option>
                        </select>

                        <button type="submit" disabled={loading} className="search-button">
                            {loading ? <span className="loader"></span> : 'Analyze'}
                        </button>
                    </div>
                </form>
            </div>

            {error && <div className="error-message">{error}</div>}

            {result && (
                <div className="result-section">
                    <div className="result-header">
                        <h2>Analysis Result for {stockName}</h2>
                    </div>

                    <div className="table-container">
                        <table className="results-table">
                            <thead>
                                <tr>
                                    <th>Check Name</th>
                                    <th>Pass/Fail</th>
                                    <th>Reason</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td>Fundamentals</td>
                                    <td>
                                        <span className={`status-text ${result.result_1 === 'pass' ? 'pass' : 'fail'}`}>
                                            {result.result_1?.toUpperCase()}
                                        </span>
                                    </td>
                                    <td>{result.reason_1 || 'Fundamentals meet the high-quality benchmarks set in the system.'}</td>
                                </tr>
                                <tr>
                                    <td>45-Degree Check</td>
                                    <td>
                                        <span className={`status-text ${result.result_2 === 'pass' ? 'pass' : 'fail'}`}>
                                            {result.result_2?.toUpperCase()}
                                        </span>
                                    </td>
                                    <td>{result.reason_2 || 'Price trend analysis complete.'}</td>
                                </tr>
                                {result.stage_analysis && result.stage_analysis[0] && (
                                    <tr>
                                        <td>Weinstein Stage</td>
                                        <td>
                                            <span className="status-text status-badge">
                                                STAGE {result.stage_analysis[0].Stage}
                                            </span>
                                        </td>
                                        <td>
                                            <strong>{result.stage_analysis[0].Actionable_Advice}</strong>
                                            <br />
                                            <small>{result.stage_analysis[0].Remarks}</small>
                                        </td>
                                    </tr>
                                )}
                                {result.stage_analysis_error && (
                                    <tr>
                                        <td>Weinstein Stage</td>
                                        <td><span className="status-text fail">ERROR</span></td>
                                        <td>{result.stage_analysis_error}</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>

                    <div className="data-section">
                        <h3>Raw Financial Data</h3>
                        <pre className="json-display">
                            {JSON.stringify(result.financial_data, null, 2)}
                        </pre>
                    </div>
                </div>
            )}
        </div>
    );
};

export default AnalyzePage;
