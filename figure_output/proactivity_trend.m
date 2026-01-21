%% Proactivity Trend (turn-level): Mean trend over normalized session progress (NO heterogeneity shown)
% MATLAB R2025a
%
% Input per benchmark: one turns-level Excel (e.g., results_turns.xlsx)
% Required columns (case-insensitive):
%   - user_id
%   - session_id
%   - assistant_turn_index   (turn index resets to 1 for each session)
%   - score                  (0/1/2)
%
% Optional columns (case-insensitive):
%   - agenda_move_type       (if exists, filter out agenda_move_type == 'none')
%   - status_code            (if exists, keep status_code==200)
%   - parse_error            (if exists, drop non-empty parse_error rows)
%
% Method:
%   For each (user, session):
%     progress = (assistant_turn_index - 1) / (max_turn_in_session - 1) in [0,1]
%   Bin progress into K bins and compute per-user mean score per bin across all sessions.
%   Aggregate across users -> mean + 95% CI.
%   Optional smoothing for both mean and CI width.

clear; clc;

% -------------------- USER CONFIG --------------------
xlsxFiles  = { ...
    'eval_results\eval_proactivity_mode0\results_turns.xlsx', ...   % Benchmark A (replace)
    'eval_results\eval_proactivity_mode1\results_turns.xlsx', ...   % Benchmark B (replace)
    'eval_results\eval_proactivity_mode2\results_turns.xlsx'  ...   % Benchmark C (replace)
};

benchNames = {'SSC','MSS','SA'};
nBench = numel(xlsxFiles);

K = 40;                    % number of progress bins (e.g., 30/40)
smoothMethod = 'movmean';  % 'movmean' or 'gaussian'
smoothWindow = 5;          % e.g., 5/7 (<=K)
z = 1.96;                  % ~95% CI
% -----------------------------------------------------

% -------------------- STYLE ---------------------------
fontName      = 'Helvetica';
axFontSize    = 16;
labelFontSize = 17.6;
legFontSize   = 16;

cBlue   = [0.0353, 0.5176, 0.8902];
cRed    = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
colors  = [cRed; cBlue; cOrange];   % A/B/C
% -----------------------------------------------------

% -------------------- LOAD ALL FILES ------------------
Tbench = cell(nBench,1);
allUsers = strings(0,1);

for b = 1:nBench
    Tbench{b} = load_turn_table(xlsxFiles{b});      % includes agenda_move_type filtering if present
    allUsers  = union(allUsers, unique(Tbench{b}.user_id));
end

allUsers = sort(allUsers);
nUsers = numel(allUsers);

% -------------------- BUILD USER x BENCH x BIN MATRIX --------------------
% B(u,b,k) = per-user mean score at progress bin k for benchmark b
B = NaN(nUsers, nBench, K);

for b = 1:nBench
    Tb = Tbench{b};

    for u = 1:nUsers
        uid = allUsers(u);
        Tu = Tb(Tb.user_id == uid, :);
        if isempty(Tu), continue; end

        % Compute bin index for each turn based on per-session normalized progress
        binIdxAll = zeros(height(Tu),1);

        % Group within this user by session_id (turn index resets each session)
        [G, sessList] = findgroups(Tu.session_id); %#ok<ASGLU>
        for si = 1:max(G)
            rows = (G == si);
            t = Tu.assistant_turn_index(rows);
            smax = max(t);

            if smax <= 1
                prog = zeros(sum(rows),1);
            else
                prog = (t - 1) / (smax - 1);  % 0..1
            end

            % Map progress -> bins 1..K
            binIdxAll(rows) = min(K, max(1, floor(prog * K) + 1));
        end

        % Aggregate this user's scores within each bin across all sessions
        sc = Tu.score;
        for k = 1:K
            sel = (binIdxAll == k);
            if any(sel)
                B(u,b,k) = mean(sc(sel), 'omitnan');
            end
        end
    end
end

% -------------------- AGGREGATE ACROSS USERS --------------------
mu   = squeeze(mean(B, 1, 'omitnan'));          % nBench x K
sd   = squeeze(std(B,  0, 1, 'omitnan'));       % nBench x K
nEff = squeeze(sum(~isnan(B), 1));              % nBench x K
se   = sd ./ sqrt(max(nEff, 1));                % nBench x K
ci95 = z * se;

% Smooth mean and SE (recommended)
mu_sm = zeros(size(mu));
se_sm = zeros(size(se));
for b = 1:nBench
    mu_sm(b,:) = smoothdata(mu(b,:), 2, smoothMethod, smoothWindow, 'omitnan');
    se_sm(b,:) = smoothdata(se(b,:), 2, smoothMethod, smoothWindow, 'omitnan');
end
ci95_sm = z * se_sm;

% X in percentage
x = (1:K) / K * 100;

% -------------------- PLOT --------------------
fig = figure('Color','w','Position',[100 100 1000 520]);
ax  = axes(fig); hold(ax,'on');

hLine = gobjects(1,nBench);

for b = 1:nBench
    y  = mu_sm(b,:);
    lo = y - ci95_sm(b,:);
    hi = y + ci95_sm(b,:);

    hBand = fill(ax, [x, fliplr(x)], [lo, fliplr(hi)], colors(b,:), ...
        'FaceAlpha', 0.18, 'EdgeColor', 'none');
    set(hBand, 'HandleVisibility', 'off');

    hLine(b) = plot(ax, x, y, '-o', ...
        'LineWidth', 3, 'MarkerSize', 5, 'Color', colors(b,:));
end

xlim(ax, [0 100]);
ylim(ax, [0 2]);
xticks(ax, 0:20:100);
xticklabels(ax, compose('%d%%', 0:20:100));
yticks(ax, 0:1:2);

xlabel(ax, 'Session Progress', 'FontName', fontName, ...
    'FontSize', labelFontSize, 'FontWeight', 'bold');
ylabel(ax, 'Mean Proactivity Score', 'FontName', fontName, ...
    'FontSize', labelFontSize, 'FontWeight', 'bold');

set(ax, 'FontName', fontName, 'FontSize', axFontSize, ...
    'FontWeight', 'bold', 'LineWidth', 1);
grid(ax, 'on');
box(ax, 'off');

leg = legend(ax, hLine, benchNames, ...
    'Orientation','horizontal', 'NumColumns', 3, 'Location','northoutside');
set(leg, 'Box','on', 'FontName',fontName, 'FontSize',legFontSize, 'FontWeight','bold');

% Optional export
% exportgraphics(fig, 'proactivity_trend.png', 'Resolution', 300);
% exportgraphics(fig, 'proactivity_trend.pdf', 'ContentType', 'vector');

%% -------------------- LOCAL FUNCTION --------------------
function T = load_turn_table(xlsxPath)
%LOAD_TURN_TABLE Read turns-level proactivity file and return standardized table.
% Output columns:
%   user_id (string), session_id (string), assistant_turn_index (double), score (double)
%
% Filtering rules:
% - If agenda_move_type exists: drop rows where lower(trim(agenda_move_type)) == "none"
%   (These are typically termination/exit turns and should not affect proactivity trends.)
% - If status_code exists: keep status_code==200
% - If parse_error exists: drop non-empty parse_error rows

    assert(isfile(xlsxPath), 'Excel file not found: %s', xlsxPath);

    T0 = readtable(xlsxPath, 'VariableNamingRule','preserve');
    vars = string(T0.Properties.VariableNames);
    varsLower = lower(vars);

    iUser = find(varsLower == "user_id", 1);
    iSess = find(varsLower == "session_id", 1);
    iTurn = find(varsLower == "assistant_turn_index", 1);
    iSc   = find(varsLower == "score", 1);

    assert(~isempty(iUser), 'Missing column "user_id" in %s', xlsxPath);
    assert(~isempty(iSess), 'Missing column "session_id" in %s', xlsxPath);
    assert(~isempty(iTurn), 'Missing column "assistant_turn_index" in %s', xlsxPath);
    assert(~isempty(iSc),   'Missing column "score" in %s', xlsxPath);

    user = string(T0.(vars(iUser)));
    sess = string(T0.(vars(iSess)));
    turn = double(T0.(vars(iTurn)));
    sc   = double(T0.(vars(iSc)));

    % Base validity
    valid = ~ismissing(user) & ~ismissing(sess) & isfinite(turn) & isfinite(sc);

    % Optional: status_code == 200
    iStatus = find(varsLower == "status_code", 1);
    if ~isempty(iStatus)
        statusCode = T0.(vars(iStatus));
        valid = valid & ~ismissing(statusCode) & (statusCode == 200);
    end

    % Optional: parse_error empty
    iParse = find(varsLower == "parse_error", 1);
    if ~isempty(iParse)
        pe = T0.(vars(iParse));
        okParse = true(height(T0),1);

        if iscell(pe)
            okParse = cellfun(@(x) isempty(x) || (ischar(x) && isempty(strtrim(x))) || (isstring(x) && strlength(x)==0), pe);
        elseif isstring(pe)
            okParse = ismissing(pe) | (strlength(pe)==0);
        end

        valid = valid & okParse;
    end

    % Optional: drop agenda_move_type == 'none'
    iAgenda = find(varsLower == "agenda_move_type", 1);
    if ~isempty(iAgenda)
        agenda = string(T0.(vars(iAgenda)));
        agenda = lower(strtrim(agenda));
        % Keep rows where agenda is not "none" (missing agenda is kept)
        keepAgenda = ismissing(agenda) | (agenda ~= "none");
        valid = valid & keepAgenda;
    end

    % Apply validity mask
    user = lower(strtrim(user(valid)));
    sess = strtrim(sess(valid));
    turn = turn(valid);
    sc   = sc(valid);

    % Keep only scores in {0,1,2}
    okScore = (sc==0) | (sc==1) | (sc==2);
    user = user(okScore);
    sess = sess(okScore);
    turn = turn(okScore);
    sc   = sc(okScore);

    T = table(user, sess, turn, sc, ...
        'VariableNames', {'user_id','session_id','assistant_turn_index','score'});
end
