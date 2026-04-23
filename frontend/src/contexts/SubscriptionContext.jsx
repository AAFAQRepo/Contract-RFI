import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import api from '../api/client';

const SubscriptionContext = createContext();

export const useSubscription = () => useContext(SubscriptionContext);

export const SubscriptionProvider = ({ children }) => {
  const [usage, setUsage] = useState({ documents: 0, queries: 0, limit: 5 });
  const [plan, setPlan] = useState('free');

  const refreshUsage = useCallback(async () => {
    try {
      const res = await api.get('/workspace/usage');
      setUsage(res.data);
    } catch (err) {
      console.error('Failed to fetch usage', err);
    }
  }, []);

  useEffect(() => {
    refreshUsage();
  }, [refreshUsage]);

  return (
    <SubscriptionContext.Provider value={{ subscription: { usage, plan }, refreshUsage }}>
      {children}
    </SubscriptionContext.Provider>
  );
};
