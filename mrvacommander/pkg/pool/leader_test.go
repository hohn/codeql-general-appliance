package pool

import (
	"errors"
	"testing"
	"time"

	"github.com/hohn/mrvacommander/pkg/state"
)

type fakeLeaderState struct {
	acquired    bool
	renewed     bool
	holder      state.SchedulerLockHolder
	acquireErr  error
	renewErr    error
	releaseErr  error
	releaseCall int
	releasedID  string
}

func (f *fakeLeaderState) AcquireSchedulerLock(_ string, leaseID, serverID string, _ int, _ *time.Time, lastHolder *state.SchedulerLockHolder, _ time.Duration) (bool, error) {
	if f.acquireErr != nil {
		return false, f.acquireErr
	}
	if f.acquired {
		f.holder = state.SchedulerLockHolder{LeaseID: leaseID, ServerID: serverID}
	}
	*lastHolder = f.holder
	return f.acquired, nil
}

func (f *fakeLeaderState) RenewSchedulerLock(_ string, _ string, _ int, _ *time.Time, _ time.Duration) (bool, error) {
	return f.renewed, f.renewErr
}

func (f *fakeLeaderState) ReleaseSchedulerLock(_ string, leaseID string) error {
	f.releaseCall++
	f.releasedID = leaseID
	return f.releaseErr
}

func (f *fakeLeaderState) RegisterServer(_, _ string) error {
	return nil
}

func (f *fakeLeaderState) ServerHeartbeat(_, _ string) error {
	return nil
}

func newElectionTestPool(election *fakeLeaderState) *PoolManager {
	serverID := "server-a"
	return &PoolManager{
		config: Config{
			LeaderLeaseDuration: 30 * time.Second,
		},
		leaderState: election,
		registry:    election,
		serverID:    serverID,
		leaseID:     "lease-a",
		status: ServerStatus{
			InstanceID: serverID,
			Role:       ServerRoleBackup,
			LockName:   leaderLockName,
		},
	}
}

func TestMaintainLeadershipAcquireRenewAndLose(t *testing.T) {
	election := &fakeLeaderState{acquired: true, renewed: true}
	manager := newElectionTestPool(election)

	if promoted := manager.maintainLeadership(); !promoted {
		t.Fatal("expected initial lease acquisition to promote server")
	}
	if got := manager.Status(); got.Role != ServerRoleLeader || got.LeaderID != "server-a" {
		t.Fatalf("unexpected leader status: %+v", got)
	}

	if held := manager.maintainLeadership(); !held {
		t.Fatal("lease renewal must report continuing ownership")
	}
	if got := manager.Status(); got.Role != ServerRoleLeader {
		t.Fatalf("renewed server lost leadership: %+v", got)
	}

	election.renewed = false
	manager.maintainLeadership()
	if got := manager.Status(); got.Role != ServerRoleBackup || got.LeaderID != "" {
		t.Fatalf("server did not become backup after losing lease: %+v", got)
	}

	election.acquired = false
	election.holder = state.SchedulerLockHolder{LeaseID: "lease-b", ServerID: "server-b"}
	manager.maintainLeadership()
	if got := manager.Status(); got.Role != ServerRoleBackup || got.LeaderID != "server-b" {
		t.Fatalf("backup did not report current leader: %+v", got)
	}
}

func TestMaintainLeadershipFailsClosed(t *testing.T) {
	election := &fakeLeaderState{
		acquired:   true,
		renewed:    true,
		renewErr:   errors.New("database unavailable"),
		releaseErr: errors.New("database unavailable"),
	}
	manager := newElectionTestPool(election)

	manager.maintainLeadership()
	manager.maintainLeadership()
	if got := manager.Status(); got.Role != ServerRoleBackup {
		t.Fatalf("renewal error must demote the server: %+v", got)
	}

	manager.releaseLeadership()
	if election.releaseCall != 1 || election.releasedID != "lease-a" {
		t.Fatalf("release calls = %d for %q, want unique lease token", election.releaseCall, election.releasedID)
	}
}

func TestReleaseLeadership(t *testing.T) {
	election := &fakeLeaderState{acquired: true}
	manager := newElectionTestPool(election)
	manager.maintainLeadership()

	manager.releaseLeadership()

	if election.releaseCall != 1 {
		t.Fatalf("release calls = %d, want 1", election.releaseCall)
	}
	if election.releasedID != "lease-a" {
		t.Fatalf("released ID = %q, want process-unique lease token", election.releasedID)
	}
	if got := manager.Status(); got.Role != ServerRoleBackup || got.LeaderID != "" {
		t.Fatalf("released server did not become backup: %+v", got)
	}
}

func TestLeaderConfigRequiresRenewalBeforeExpiry(t *testing.T) {
	t.Setenv("MRVA_POOL_LEADER_LEASE_SECONDS", "6")
	t.Setenv("MRVA_POOL_LEADER_CHECK_SECONDS", "6")

	cfg := NewConfigFromEnv()

	if cfg.LeaderLeaseDuration != 6*time.Second {
		t.Fatalf("leader lease = %s, want 6s", cfg.LeaderLeaseDuration)
	}
	if cfg.LeaderCheckInterval != 2*time.Second {
		t.Fatalf("unsafe leader check adjusted to %s, want 2s", cfg.LeaderCheckInterval)
	}
}

func TestCachedLeadershipFailsClosedAtLocalDeadline(t *testing.T) {
	election := &fakeLeaderState{acquired: true}
	manager := newElectionTestPool(election)
	manager.config.LeaderLeaseDuration = 20 * time.Millisecond

	if held := manager.maintainLeadership(); !held {
		t.Fatal("expected initial lease acquisition")
	}
	time.Sleep(25 * time.Millisecond)

	if manager.IsLeader() {
		t.Fatal("cached role remained leader after conservative local lease deadline")
	}
	if got := manager.Status(); got.Role != ServerRoleBackup || got.LeaderID != "" {
		t.Fatalf("expired local status did not fail closed: %+v", got)
	}
}
