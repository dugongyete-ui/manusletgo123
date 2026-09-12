// Agent-profile API — built-in presets + user-custom agent personas.
import { apiClient, ApiResponse } from './client';

export interface AgentProfile {
  profile_id: string;
  name: string;
  description?: string | null;
  emoji?: string | null;
  instruction: string;
  is_builtin: boolean;
}

export async function getAgentProfiles(): Promise<AgentProfile[]> {
  const response = await apiClient.get<ApiResponse<{ profiles: AgentProfile[] }>>('/agent-profiles');
  return response.data.data.profiles;
}

export async function createAgentProfile(request: {
  name: string;
  description?: string | null;
  emoji?: string | null;
  instruction: string;
}): Promise<{ profile_id: string }> {
  const response = await apiClient.post<ApiResponse<{ profile_id: string }>>(
    '/agent-profiles',
    request
  );
  return response.data.data;
}

export async function deleteAgentProfile(profileId: string): Promise<void> {
  await apiClient.delete<ApiResponse<void>>(`/agent-profiles/${profileId}`);
}

/** Public gallery of shared sessions (community). */
export interface CommunitySession {
  session_id: string;
  title: string | null;
  latest_message?: string | null;
  latest_message_at?: number | null;
}

export async function getCommunitySessions(limit = 50): Promise<CommunitySession[]> {
  const response = await apiClient.get<ApiResponse<{ sessions: CommunitySession[] }>>(
    `/community/sessions?limit=${limit}`
  );
  return response.data.data.sessions;
}

/** Fork a session (own or shared) into the current user's account. */
export async function forkSession(
  sessionId: string
): Promise<{ session_id: string; title: string | null }> {
  const response = await apiClient.post<
    ApiResponse<{ session_id: string; title: string | null }>
  >(`/sessions/${sessionId}/fork`);
  return response.data.data;
}
