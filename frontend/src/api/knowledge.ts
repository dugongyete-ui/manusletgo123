// Knowledge API — durable user knowledge + post-task learning proposals.
import { apiClient, ApiResponse } from './client';

export interface KnowledgeItem {
  knowledge_id: string;
  content: string;
  kind: 'user' | 'learning' | 'builtin';
  status: 'pending' | 'active' | 'rejected';
  source_session_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ListKnowledgeResponse {
  items: KnowledgeItem[];
}

export async function getKnowledge(): Promise<ListKnowledgeResponse> {
  const response = await apiClient.get<ApiResponse<ListKnowledgeResponse>>('/knowledge');
  return response.data.data;
}

export async function addKnowledge(content: string): Promise<{ knowledge_id: string }> {
  const response = await apiClient.post<ApiResponse<{ knowledge_id: string }>>('/knowledge', {
    content,
  });
  return response.data.data;
}

export async function setKnowledgeStatus(
  knowledgeId: string,
  status: 'active' | 'rejected' | 'pending'
): Promise<void> {
  await apiClient.patch<ApiResponse<void>>(`/knowledge/${knowledgeId}`, { status });
}

export async function deleteKnowledge(knowledgeId: string): Promise<void> {
  await apiClient.delete<ApiResponse<void>>(`/knowledge/${knowledgeId}`);
}
