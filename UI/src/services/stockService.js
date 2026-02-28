import axios from 'axios';

const API_BASE_URL = 'http://localhost:8000';

const stockService = {
    analyzeStock: async (stockName, portfolioType, purpose) => {
        try {
            const response = await axios.post(`${API_BASE_URL}/analyze/${encodeURIComponent(stockName)}`, {
                portfolio_type: portfolioType,
                purpose: purpose
            });
            return response.data;
        } catch (error) {
            console.error('Error analyzing stock:', error);
            throw error;
        }
    },
    rankAll: async (data, portfolio_type) => {
        try {
            const response = await axios.post(`${API_BASE_URL}/analyzeall/${portfolio_type}`, {
                data: data
            });
            return response.data;
        } catch (error) {
            console.error('Error ranking stocks:', error);
            throw error;
        }
    },
    clearCache: async (stockName, ticker) => {
        try {
            const response = await axios.post(`${API_BASE_URL}/cacheclear/${encodeURIComponent(stockName)}`, null, {
                params: { ticker }
            });
            return response.data;
        } catch (error) {
            console.error('Error clearing cache:', error);
            throw error;
        }
    }
};

export default stockService;
