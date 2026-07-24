// amosclaude-clean/dashboard/Dashboard.tsx
import React, { useEffect, useState } from 'react';
import { Box, Typography, Grid, Card, CardContent, CircularProgress } from '@mui/material';

interface DashboardStats {
  totalUsers: number;
  activeUsers: number;
  totalMessages: number;
  pendingTasks: number;
}

const Dashboard: React.FC = () => {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchDashboardStats = async () => {
      setLoading(true);
      setError(null);
      try {
        // In a real application, this would be an API call to your backend
        // For now, simulate a network request
        const response = await new Promise<DashboardStats>((resolve) =>
          setTimeout(() => {
            resolve({
              totalUsers: 1250,
              activeUsers: 345,
              totalMessages: 56789,
              pendingTasks: 12,
            });
          }, 1000)
        );
        setStats(response);
      } catch (err) {
        console.error("Failed to fetch dashboard stats:", err);
        setError("Failed to load dashboard data. Please try again.");
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardStats();
  }, []);

  return (
    <Box sx={{ flexGrow: 1, p: 3 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Amosclaud Dashboard
      </Typography>

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
          <CircularProgress />
          <Typography variant="h6" sx={{ ml: 2 }}>Loading Dashboard...</Typography>
        </Box>
      )}

      {error && (
        <Box sx={{ mt: 4, textAlign: 'center', color: 'error.main' }}>
          <Typography variant="h6">{error}</Typography>
        </Box>
      )}

      {stats && (
        <Grid container spacing={3}>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="textSecondary" gutterBottom>
                  Total Users
                </Typography>
                <Typography variant="h5" component="div">
                  {stats.totalUsers.toLocaleString()}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="textSecondary" gutterBottom>
                  Active Users
                </Typography>
                <Typography variant="h5" component="div">
                  {stats.activeUsers.toLocaleString()}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="textSecondary" gutterBottom>
                  Total Messages
                </Typography>
                <Typography variant="h5" component="div">
                  {stats.totalMessages.toLocaleString()}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="textSecondary" gutterBottom>
                  Pending Tasks
                </Typography>
                <Typography variant="h5" component="div">
                  {stats.pendingTasks.toLocaleString()}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          {/* Add more dashboard widgets here */}
        </Grid>
      )}
    </Box>
  );
};

export default Dashboard;

