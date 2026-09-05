// Scheduled-task API — recurring agent runs (scheduleTask).
import { apiClient, ApiResponse } from './client';

export interface ScheduledTask {
  task_id: string;
  session_id: string;
  prompt: string;
  interval_minutes: number;
  next_run_at?: string | null;
  last_run_at?: string | null;
  run_count: number;
  is_active: boolean;
  created_at?: string | null;
}

export interface CreateScheduledTaskRequest {
  prompt: string;
  session_id?: string | null;
  interval_minutes: number;
}

export async function getScheduledTasks(): Promise<ScheduledTask[]> {
  const response = await apiClient.get<ApiResponse<{ tasks: ScheduledTask[] }>>('/scheduled-tasks');
  return response.data.data.tasks;
}

export async function createScheduledTask(
  request: CreateScheduledTaskRequest
): Promise<{ task_id: string; session_id: string }> {
  const response = await apiClient.post<
    ApiResponse<{ task_id: string; session_id: string }>
  >('/scheduled-tasks', request);
  return response.data.data;
}

export async function toggleScheduledTask(
  taskId: string,
  isActive: boolean
): Promise<void> {
  await apiClient.patch<ApiResponse<void>>(`/scheduled-tasks/${taskId}`, {
    is_active: isActive,
  });
}

export async function deleteScheduledTask(taskId: string): Promise<void> {
  await apiClient.delete<ApiResponse<void>>(`/scheduled-tasks/${taskId}`);
}
