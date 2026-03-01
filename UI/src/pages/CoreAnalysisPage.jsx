import React, { useState, useRef } from 'react';
import * as XLSX from 'xlsx';
import stockService from '../services/stockService';
import './CoreAnalysisPage.css';

const CoreAnalysisPage = () => {
    const [stocks, setStocks] = useState([]);
    const [showAddPopup, setShowAddPopup] = useState(false);
    const [newStockName, setNewStockName] = useState('');
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [rawDetails, setRawDetails] = useState(null);
    const [technicalDetails, setTechnicalDetails] = useState(null);
    const [detailPopup, setDetailPopup] = useState(null);
    const [portfolioType, setPortfolioType] = useState('core');
    const fileInputRef = useRef(null);

    const createInitialStock = (name) => ({
        name,
        fundamentals: { result: '-', reason: '-' },
        trend: { result: '-', reason: '-' },
        stage: { stage: '-', remarks: '-' },
        rank: { score: '-', justification: '-' },
        ticker_name: '',
        technical_analysis: null,
        raw_financial_data: null,
        analysis_decision: { decision: '-', reasoning: '-' },
        isLoading: false,
        error: null
    });

    const handleAddStock = (e) => {
        e.preventDefault();
        if (newStockName.trim()) {
            const stockToAdd = newStockName.trim().toUpperCase();
            if (!stocks.find(s => s.name === stockToAdd)) {
                setStocks([...stocks, createInitialStock(stockToAdd)]);
            }
            setNewStockName('');
            setShowAddPopup(false);
        }
    };

    const handleDeleteStock = (name) => {
        setStocks(stocks.filter(s => s.name !== name));
    };

    const handleFileUpload = (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const isExcel = file.name.endsWith('.xlsx') || file.name.endsWith('.xls');
        const isCSV = file.name.endsWith('.csv');
        if (isExcel || isCSV) {
            const reader = new FileReader();
            reader.onload = (event) => {
                const data = event.target.result;
                let stockNames = [];
                if (isExcel) {
                    const workbook = XLSX.read(data, { type: 'binary' });
                    const worksheet = workbook.Sheets[workbook.SheetNames[0]];
                    const json = XLSX.utils.sheet_to_json(worksheet, { header: 1 });
                    stockNames = json.map(row => row[0]).filter(Boolean);
                } else {
                    stockNames = data.split('\n').map(row => row.split(',')[0].trim());
                }
                const cleaned = stockNames
                    .map(n => String(n).toUpperCase())
                    .filter(n => n && n !== 'STOCK NAME' && n !== 'TICKER' && !stocks.find(s => s.name === n));
                setStocks([...stocks, ...cleaned.map(n => createInitialStock(n))]);
                e.target.value = '';
            };
            isExcel ? reader.readAsBinaryString(file) : reader.readAsText(file);
        } else {
            alert('Please upload a valid CSV or Excel file.');
        }
    };

    const handleClear = () => {
        if (window.confirm('Are you sure you want to clear the entire watchlist?')) {
            setStocks([]);
        }
    };

    const handleAnalyze = async () => {
        if (stocks.length === 0 || isAnalyzing) return;
        setIsAnalyzing(true);
        try {
            const updatedStocks = [...stocks];

            // Phase 1: Sequential per-stock analysis
            for (let i = 0; i < updatedStocks.length; i++) {
                const stock = updatedStocks[i];
                updatedStocks[i] = { ...stock, isLoading: true, error: null };
                setStocks([...updatedStocks]);
                try {
                    const r = await stockService.analyzeStock(stock.name, portfolioType, 'buy');

                    // Defensive binding — handle result/result_1, reason/reason_1 shapes
                    const fundResult = r.result_1 || r.result || '-';
                    const fundReason = r.reason_1 || r.reason || '-';
                    const trendResult = r.result_2 || '-';
                    const trendReason = r.reason_2 || '-';

                    // stage_analysis can be an array or an object with Stage key
                    let stageStage = '-';
                    let stageRemarks = '-';
                    if (r.stage_analysis) {
                        const sa = Array.isArray(r.stage_analysis)
                            ? r.stage_analysis[0]
                            : r.stage_analysis;
                        stageStage = sa?.Stage ?? sa?.stage ?? '-';
                        stageRemarks = sa?.Remarks ?? sa?.remarks ?? sa?.Actionable_Advice ?? '-';
                    }

                    updatedStocks[i] = {
                        ...updatedStocks[i],
                        isLoading: false,
                        fundamentals: { result: fundResult, reason: fundReason },
                        trend: { result: trendResult, reason: trendReason },
                        stage: { stage: stageStage, remarks: stageRemarks },
                        ticker_name: r.ticker_name || '',
                        technical_analysis: r.technical_analysis || null,
                        raw_financial_data: r.financial_data || null,
                        analysis_decision: r.analysis_decision || { decision: '-', reasoning: '-' }
                    };
                } catch (err) {
                    updatedStocks[i] = { ...updatedStocks[i], isLoading: false, error: 'Analysis failed' };
                }
                setStocks([...updatedStocks]);

                // 10-second delay between stocks to avoid hitting API rate limits
                if (i < updatedStocks.length - 1) {
                    await new Promise(resolve => setTimeout(resolve, 10000));
                }
            }

            // Phase 2: Batch Ranking
            try {
                const batchInput = updatedStocks
                    .filter(s => s.raw_financial_data)
                    .map(s => ({
                        StockName: s.name,
                        Financials: s.raw_financial_data,
                        Stage: s.stage.stage,
                        StageReason: s.stage.remarks
                    }));

                if (batchInput.length > 0) {
                    const rankingResults = await stockService.rankAll(
                        batchInput.map(s => ({
                            name: s.StockName,
                            financial_data: s.Financials,
                            stage_analysis: s.Stage
                        })),
                        portfolioType
                    );
                    const ranks = rankingResults.ranking_results || [];
                    const finalizedStocks = updatedStocks.map(s => {
                        const rankData = ranks.find(r =>
                            (r.StockName || r.stock_name || r.name || '').toUpperCase() === s.name.toUpperCase()
                        );
                        if (rankData) {
                            return {
                                ...s,
                                rank: {
                                    score: rankData.score ?? rankData.rank ?? '?',
                                    justification: rankData.justification || rankData.reason || '-'
                                }
                            };
                        }
                        return s;
                    });
                    setStocks(finalizedStocks);
                }
            } catch (err) {
                console.error('Batch ranking failed:', err);
            }
        } catch (globalErr) {
            console.error('Batch analysis error:', globalErr);
        } finally {
            setIsAnalyzing(false);
        }
    };

    const handleRowAnalyze = async (stockName) => {
        if (isAnalyzing) return;
        setIsAnalyzing(true);

        const updatedStocks = [...stocks];
        const stockIndex = updatedStocks.findIndex(s => s.name === stockName);
        if (stockIndex === -1) {
            setIsAnalyzing(false);
            return;
        }

        updatedStocks[stockIndex] = { ...updatedStocks[stockIndex], isLoading: true, error: null };
        setStocks([...updatedStocks]);

        try {
            const r = await stockService.analyzeStock(stockName, portfolioType, 'buy');

            // Reusing defensive binding logic
            const fundResult = r.result_1 || r.result || '-';
            const fundReason = r.reason_1 || r.reason || '-';
            const trendResult = r.result_2 || '-';
            const trendReason = r.reason_2 || '-';

            let stageStage = '-';
            let stageRemarks = '-';
            if (r.stage_analysis) {
                const sa = Array.isArray(r.stage_analysis) ? r.stage_analysis[0] : r.stage_analysis;
                stageStage = sa?.Stage ?? sa?.stage ?? '-';
                stageRemarks = sa?.Remarks ?? sa?.remarks ?? sa?.Actionable_Advice ?? '-';
            }

            updatedStocks[stockIndex] = {
                ...updatedStocks[stockIndex],
                isLoading: false,
                fundamentals: { result: fundResult, reason: fundReason },
                trend: { result: trendResult, reason: trendReason },
                stage: { stage: stageStage, remarks: stageRemarks },
                ticker_name: r.ticker_name || '',
                technical_analysis: r.technical_analysis || null,
                raw_financial_data: r.financial_data || null,
                analysis_decision: r.analysis_decision || { decision: '-', reasoning: '-' }
            };
        } catch (err) {
            console.error(`Analysis failed for ${stockName}:`, err);
            updatedStocks[stockIndex] = { ...updatedStocks[stockIndex], isLoading: false, error: 'Analysis failed' };
        } finally {
            setStocks([...updatedStocks]);
            setIsAnalyzing(false);
        }
    };

    const handleChat = (stockName) => {
        alert(`Chat with ${stockName} coming soon!`);
    };

    const handleClearCache = async (stock) => {
        if (isAnalyzing) return;
        try {
            await stockService.clearCache(stock.name, stock.ticker_name);
            alert(`Cache cleared for ${stock.name}`);
            // Optionally reset the row state to '-' if we want to force re-analysis visual
            const updatedStocks = [...stocks];
            const idx = updatedStocks.findIndex(s => s.name === stock.name);
            if (idx !== -1) {
                updatedStocks[idx] = createInitialStock(stock.name);
                setStocks(updatedStocks);
            }
        } catch (err) {
            console.error(`Failed to clear cache for ${stock.name}:`, err);
            alert('Failed to clear cache');
        }
    };

    const openDetail = (title, content) => setDetailPopup({ title, content });

    const DetailIcon = ({ title, content }) =>
        content && content !== '-'
            ? <button className="detail-icon-btn" onClick={() => openDetail(title, content)} title={title}>＋</button>
            : <span className="muted">—</span>;

    return (
        <div className="core-container">
            <header className="core-header">
                <h1 className="title">Core <span>Analysis</span> Dashboard</h1>
                <p className="subtitle">Manage and perform batch  analysis on your watchlist</p>
            </header>

            <div className="actions-bar">
                <div className="header-actions">
                    <div className="portfolio-tabs">
                        <button
                            className={`tab-btn ${portfolioType === 'core' ? 'active' : ''}`}
                            onClick={() => setPortfolioType('core')}
                            disabled={isAnalyzing}
                        >
                            Core
                        </button>
                        <button
                            className={`tab-btn ${portfolioType === 'sattelite' ? 'active' : ''}`}
                            onClick={() => setPortfolioType('sattelite')}
                            disabled={isAnalyzing}
                        >
                            Sattelite
                        </button>
                    </div>
                    <button
                        className="btn btn-secondary" onClick={() => setShowAddPopup(true)} disabled={isAnalyzing}>
                        <span className="icon">+</span> Add Stock
                    </button>
                    <button className="btn btn-secondary" onClick={() => fileInputRef.current.click()} disabled={isAnalyzing}>
                        <span className="icon">↑</span> Upload (CSV/XLS/XLSX)
                    </button>
                    <button className="btn btn-secondary clear-btn" onClick={handleClear} disabled={isAnalyzing}>
                        <span className="icon">🗑</span> Clear
                    </button>
                    <input type="file" ref={fileInputRef} style={{ display: 'none' }} accept=".csv,.xlsx,.xls" onChange={handleFileUpload} />
                </div>
                <button
                    className={`btn btn-primary analyze-btn ${isAnalyzing ? 'loading' : ''}`}
                    onClick={handleAnalyze}
                    disabled={isAnalyzing || stocks.length === 0}
                >
                    {isAnalyzing ? 'Analyzing...' : 'Analyze All'}
                </button>
            </div>

            <div className="table-wrapper">
                <table className="core-results-table">
                    <thead>
                        <tr>
                            <th>Stock</th>
                            <th>Fund.</th>
                            <th>Fund. Detail</th>
                            <th>Trend</th>
                            <th>Trend Detail</th>
                            <th>Stage</th>
                            <th>Stage Detail</th>
                            <th>Rank</th>
                            <th>Decision</th>
                            <th>Reasoning</th>
                            <th>Technical</th>
                            <th>Raw Data</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {stocks.map((stock) => (
                            <tr key={stock.name} className={stock.isLoading ? 'row-loading' : ''} data-ticker={stock.ticker_name}>
                                <td className="stock-name-cell">
                                    <div className="stock-info">
                                        {stock.isLoading && <div className="spinner-small"></div>}
                                        <span>{stock.name}</span>
                                    </div>
                                    {!isAnalyzing && (
                                        <button className="delete-btn" onClick={() => handleDeleteStock(stock.name)}>×</button>
                                    )}
                                </td>
                                <td>
                                    <span className={`status-badge ${stock.fundamentals.result?.toLowerCase()}`}>
                                        {stock.fundamentals.result}
                                    </span>
                                </td>
                                <td className="action-cell">
                                    <DetailIcon title={`${stock.name} — Fundamentals`} content={stock.fundamentals.reason} />
                                </td>
                                <td>
                                    <span className={`status-badge ${stock.trend.result?.toLowerCase()}`}>
                                        {stock.trend.result}
                                    </span>
                                </td>
                                <td className="action-cell">
                                    <DetailIcon title={`${stock.name} — Trend`} content={stock.trend.reason} />
                                </td>
                                <td>
                                    <span className="status-badge stage">
                                        {stock.stage.stage !== '-' ? `Stage ${stock.stage.stage}` : '-'}
                                    </span>
                                </td>
                                <td className="action-cell">
                                    <DetailIcon title={`${stock.name} — Stage Remarks`} content={stock.stage.remarks} />
                                </td>
                                <td className="rank-cell">
                                    {stock.rank.score !== '-' ? (
                                        <div className="rank-display">
                                            <span className="rank-score">{stock.rank.score}</span>
                                            <span className="rank-label">/10</span>
                                            <button className="detail-icon-btn" onClick={() => openDetail(`${stock.name} — Rank Rationale`, stock.rank.justification)}>＋</button>
                                        </div>
                                    ) : <span className="muted">—</span>}
                                </td>
                                <td>
                                    <span className={`status-badge decision-${(stock.analysis_decision?.decision || '-').toLowerCase()}`}>
                                        {stock.analysis_decision?.decision || '-'}
                                    </span>
                                </td>
                                <td className="action-cell">
                                    <DetailIcon title={`${stock.name} — Decision Reasoning`} content={stock.analysis_decision?.reasoning} />
                                </td>
                                <td className="action-cell">
                                    {stock.technical_analysis ? (
                                        <button className="info-icon-btn technical" onClick={() => setTechnicalDetails({ name: stock.name, data: stock.technical_analysis })} title="View Technical Indicators">📊</button>
                                    ) : <span className="muted">—</span>}
                                </td>
                                <td className="action-cell">
                                    {stock.raw_financial_data ? (
                                        <button className="info-icon-btn" onClick={() => setRawDetails({ name: stock.name, data: stock.raw_financial_data })} title="View Raw Financial Data">ℹ️</button>
                                    ) : <span className="muted">—</span>}
                                </td>
                                <td className="action-cell">
                                    <div className="row-actions-group">
                                        <button
                                            className="action-btn-row analyze"
                                            onClick={() => handleRowAnalyze(stock.name)}
                                            disabled={isAnalyzing}
                                            title="Analyze Stock"
                                        >
                                            ⚡
                                        </button>
                                        <button
                                            className="action-btn-row chat"
                                            onClick={() => handleChat(stock.name)}
                                            disabled={isAnalyzing}
                                            title="Chat with Stock"
                                        >
                                            💬
                                        </button>
                                        <button
                                            className="action-btn-row clear-cache"
                                            onClick={() => handleClearCache(stock)}
                                            disabled={isAnalyzing}
                                            title="Clear Cache"
                                        >
                                            🧹
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                        {stocks.length === 0 && (
                            <tr>
                                <td colSpan="13" className="empty-message">
                                    No stocks added. Add manually or upload a file to get started.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            {/* Add Stock Modal */}
            {showAddPopup && (
                <div className="modal-overlay" onClick={() => setShowAddPopup(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <h3>Add New Stock</h3>
                        <form onSubmit={handleAddStock}>
                            <input type="text" placeholder="Enter Stock Name (e.g. RELIANCE)" value={newStockName} onChange={(e) => setNewStockName(e.target.value)} autoFocus className="modal-input" />
                            <div className="modal-actions">
                                <button type="button" className="btn btn-text" onClick={() => setShowAddPopup(false)}>Cancel</button>
                                <button type="submit" className="btn btn-primary">Add to List</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Detail Popup for Reason / Remarks / Rationale */}
            {detailPopup && (
                <div className="modal-overlay" onClick={() => setDetailPopup(null)}>
                    <div className="modal-content detail-modal" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3>{detailPopup.title}</h3>
                            <button className="close-btn" onClick={() => setDetailPopup(null)}>×</button>
                        </div>
                        <p className="detail-text">{detailPopup.content}</p>
                    </div>
                </div>
            )}

            {/* Raw Financial Data Modal */}
            {rawDetails && (
                <div className="modal-overlay" onClick={() => setRawDetails(null)}>
                    <div className="modal-content raw-data-modal" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3>Raw Financial Data: {rawDetails.name}</h3>
                            <button className="close-btn" onClick={() => setRawDetails(null)}>×</button>
                        </div>
                        <div className="raw-data-scroll">
                            <pre>{JSON.stringify(rawDetails.data, null, 2)}</pre>
                        </div>
                    </div>
                </div>
            )}

            {/* Technical Analysis Modal */}
            {technicalDetails && (
                <div className="modal-overlay" onClick={() => setTechnicalDetails(null)}>
                    <div className="modal-content ta-modal" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3>Technical Indicators: {technicalDetails.name}</h3>
                            <button className="close-btn" onClick={() => setTechnicalDetails(null)}>×</button>
                        </div>
                        <div className="ta-data-scroll">
                            <div className="ta-grid">
                                <div className="ta-section">
                                    <h4>Moving Averages (SMA/EMA)</h4>
                                    <table className="ta-sub-table">
                                        <thead><tr><th>Period</th><th>SMA</th><th>EMA</th></tr></thead>
                                        <tbody>
                                            <tr><td>20</td><td>{technicalDetails.data.indicators.sma.sma_20 || '-'}</td><td>{technicalDetails.data.indicators.ema.ema_20 || '-'}</td></tr>
                                            <tr><td>30</td><td>{technicalDetails.data.indicators.sma.sma_30 || '-'}</td><td>{technicalDetails.data.indicators.ema.ema_30 || '-'}</td></tr>
                                            <tr><td>50</td><td>{technicalDetails.data.indicators.sma.sma_50 || '-'}</td><td>{technicalDetails.data.indicators.ema.ema_50 || '-'}</td></tr>
                                        </tbody>
                                    </table>
                                </div>
                                <div className="ta-section">
                                    <h4>RSI & Strength</h4>
                                    <div className="ta-metric"><strong>RSI:</strong> <span>{technicalDetails.data.indicators.rsi.rsi || '-'}</span></div>
                                    <div className="ta-metric"><strong>RSI SMA:</strong> <span>{technicalDetails.data.indicators.rsi.rsi_sma || '-'}</span></div>
                                    <div className="ta-metric"><strong>ADX:</strong> <span>{technicalDetails.data.indicators.adx.adx || '-'}</span></div>
                                    <div className="ta-metric"><strong>Trend:</strong> <span>{technicalDetails.data.indicators.adx.adx > 25 ? 'Strong' : 'Weak/Range'}</span></div>
                                </div>
                                <div className="ta-section">
                                    <h4>Trend Indicators</h4>
                                    <div className="ta-metric"><strong>PSAR:</strong> <span>{technicalDetails.data.indicators.psar.psar || '-'} ({technicalDetails.data.indicators.psar.psar_trend})</span></div>
                                    <div className="ta-metric"><strong>SuperTrend:</strong> <span>{technicalDetails.data.indicators.supertrend.supertrend || '-'} ({technicalDetails.data.indicators.supertrend.supertrend_trend})</span></div>
                                </div>
                                <div className="ta-section">
                                    <h4>Donchian Channels</h4>
                                    <div className="ta-metric"><strong>Upper:</strong> <span>{technicalDetails.data.indicators.donchian.upper || '-'}</span></div>
                                    <div className="ta-metric"><strong>Middle:</strong> <span>{technicalDetails.data.indicators.donchian.middle || '-'}</span></div>
                                    <div className="ta-metric"><strong>Lower:</strong> <span>{technicalDetails.data.indicators.donchian.lower || '-'}</span></div>
                                    <div className="ta-metric">
                                        <strong>Slope:</strong>
                                        <span className={`trend-${technicalDetails.data.indicators.donchian_slope.slope_direction}`}>
                                            {technicalDetails.data.indicators.donchian_slope.slope_pct?.toFixed(2)}% ({technicalDetails.data.indicators.donchian_slope.slope_direction})
                                        </span>
                                    </div>
                                </div>
                                <div className="ta-section">
                                    <h4>Candle Analysis</h4>
                                    <div className="ta-metric"><strong>Type:</strong> <span className={`candle-${technicalDetails.data.indicators.candle_wick.candle_type}`}>{technicalDetails.data.indicators.candle_wick.candle_type}</span></div>
                                    <div className="ta-metric"><strong>Body:</strong> <span>{technicalDetails.data.indicators.candle_wick.body_pct}%</span></div>
                                    {technicalDetails.data.indicators.candle_wick.is_hammer && <div className="ta-tag bull">🔨 Hammer</div>}
                                    {technicalDetails.data.indicators.candle_wick.is_shooting_star && <div className="ta-tag bear">🌠 Shooting Star</div>}
                                    {technicalDetails.data.indicators.candle_wick.is_doji && <div className="ta-tag">⚖️ Doji</div>}
                                </div>
                            </div>
                            <div className="ta-footer">
                                <span>Source: {technicalDetails.data.data_source}</span>
                                <span>As of: {technicalDetails.data.as_of}</span>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default CoreAnalysisPage;
