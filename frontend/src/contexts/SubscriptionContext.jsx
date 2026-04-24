import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import api from '../api/client';

const SubscriptionContext = createContext();

export const useSubscription = () => useContext(SubscriptionContext);

export const SubscriptionProvider = ({ children }) => {
  const [usage, setUsage] = useState({ documents: 0, queries: 0, limit: 50 });
  const [plan, setPlan] = useState('free');

  const refreshUsage = useCallback(async () => {
    // Don't attempt if there's no token — avoids guaranteed 401 on cold load
    if (!localStorage.getItem('token')) return;
    try {
      const res = await api.get('/workspace/usage');
      setUsage(res.data);
      if (res.data.plan) setPlan(res.data.plan);
    } catch (err) {
      // Only log non-401 errors. 401 means not yet authenticated — handled by interceptor.
      if (err.response?.status !== 401) {
        console.error('Failed to fetch usage', err);
      }
    }
  }, []);

  useEffect(() => {
    // Delay slightly to give AuthContext time to restore token from localStorage
    const timer = setTimeout(() => refreshUsage(), 300);
    return () => clearTimeout(timer);
  }, [refreshUsage]);

  return (
    <SubscriptionContext.Provider value={{ subscription: { usage, plan }, refreshUsage }}>
      {children}
    </SubscriptionContext.Provider>
  );
};
